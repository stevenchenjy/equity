#!/usr/bin/env python3
"""Inventory Phase 5R replay-corpus readiness without I/O side effects.

This command reads local files and prints one deterministic JSON report to
stdout.  It never creates the corpus root, opens a network connection, reads
authentication state, or writes a report file.  Redirecting stdout, if wanted,
is an explicit operator action outside this program.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

# The inventory boundary includes interpreter cache files: importing the local
# validators must not create or refresh ``__pycache__``.
sys.dont_write_bytecode = True

from phase5r_sec_acceptance import validate_acceptance_index
from phase5r_strict_replay_artifacts import (
    companyfacts_paths,
    submission_paths,
    validate_companyfacts_snapshot,
    validate_exhibit_manifest,
    validate_submission_snapshot,
    validate_xbrl_reconciliation,
)
from prepare_phase5r_llm_replay_corpus import (
    CORPUS_ROOT,
    DEFAULT_CANDIDATE_PADDING,
    LEDGER_PATH,
    MAX_INDEX_BYTES,
    MAX_MARKET_BYTES,
    MAX_PRIMARY_BYTES,
    MINIMUM_REAL_ISSUERS,
    MINIMUM_REAL_PACKETS,
    CorpusError,
    canonical_sha256,
    filing_paths,
    read_ledger,
    select_candidate_rows,
    sha256_bytes,
)


ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_INDEX_PATH = (
    ROOT
    / "03_source_data"
    / "phase5r"
    / "phase5r_sec_submission_acceptance_index.json"
)
DAILY_ARTIFACT_INDEX_PATH = (
    ROOT
    / "03_source_data"
    / "phase5r"
    / "phase5r_sec_filing_artifact_index.json"
)

SCHEMA_VERSION = "phase5r_llm_replay_readiness_inventory_v1"
SELECTION_POLICY = "deterministic_round_robin_by_ticker_recent_first_v1"
DEFAULT_PILOT_PACKETS = 30
QUALIFICATION_MINIMUM_ISSUERS = MINIMUM_REAL_ISSUERS

# These are inventory planning assumptions, not newly enabled download limits.
# The current builder's enforced SEC/market caps are imported above.
MAX_EXHIBITS_PER_ACCESSION_PLANNING = 10
MAX_EXHIBIT_BYTES_PLANNING = MAX_PRIMARY_BYTES
MAX_XBRL_ISSUER_BYTES_PLANNING = 50 * 1024 * 1024
NORMALIZED_COPY_RESERVE_BYTES = MAX_PRIMARY_BYTES
PACKET_AND_METADATA_RESERVE_BYTES = 1024 * 1024
TYPICAL_INDEX_BYTES = 256 * 1024
TYPICAL_MARKET_BYTES_PER_ISSUER = 2 * 1024 * 1024
TYPICAL_EXHIBIT_BYTES = 1024 * 1024
TYPICAL_XBRL_BYTES_PER_ISSUER = 10 * 1024 * 1024
DEFAULT_TYPICAL_PRIMARY_AND_NORMALIZED_BYTES = 2 * 1024 * 1024

XBRL_FORMS = frozenset(
    {
        "10-K",
        "10-K/A",
        "10-Q",
        "10-Q/A",
        "20-F",
        "20-F/A",
        "40-F",
        "40-F/A",
    }
)
EXHIBIT_DISCOVERY_FORMS = frozenset(
    {
        "6-K",
        "6-K/A",
        "8-K",
        "8-K/A",
    }
)


def _relative_or_absolute(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _is_safe_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _is_safe_path_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return False
    current = root.absolute()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


def _safe_project_path(relative_path: Any, project_root: Path) -> Path | None:
    text = str(relative_path or "").strip()
    if not text:
        return None
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    unresolved = project_root / relative
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError:
        return None
    if not _is_safe_path_under_root(unresolved, project_root):
        return None
    return unresolved


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not _is_safe_regular_file(path):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _file_observation(
    path: Path,
    *,
    project_root: Path,
    expected_sha256: Any = None,
) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "path": _relative_or_absolute(path, project_root),
        "present": False,
        "safe_regular_file": False,
        "bytes": 0,
        "sha256": None,
        "expected_sha256": (
            str(expected_sha256)
            if isinstance(expected_sha256, str) and expected_sha256
            else None
        ),
        "hash_verified": False,
    }
    if (
        not _is_safe_regular_file(path)
        or not _is_safe_path_under_root(path, project_root)
    ):
        return observation
    try:
        raw = path.read_bytes()
    except OSError:
        return observation
    digest = sha256_bytes(raw)
    observation.update(
        {
            "present": True,
            "safe_regular_file": True,
            "bytes": len(raw),
            "sha256": digest,
            "hash_verified": (
                observation["expected_sha256"] is not None
                and digest == observation["expected_sha256"]
            ),
        }
    )
    return observation


def _raw_ledger_items(path: Path) -> dict[str, tuple[str, ...]]:
    if not _is_safe_regular_file(path):
        raise CorpusError(f"evidence ledger missing or unsafe: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if "accession_number" not in (reader.fieldnames or []):
            raise CorpusError("evidence ledger missing accession_number")
        items_by_accession: dict[str, tuple[str, ...]] = {}
        for raw in reader:
            accession = str(raw.get("accession_number", "")).strip()
            parsed = tuple(
                sorted(
                    {
                        item.strip()
                        for item in str(raw.get("items", "")).split(",")
                        if item.strip()
                    }
                )
            )
            existing = items_by_accession.get(accession)
            if existing is not None and existing != parsed:
                raise CorpusError(
                    f"conflicting ledger items for {accession}"
                )
            items_by_accession[accession] = parsed
    return items_by_accession


def _load_acceptance_freeze(
    path: Path,
    *,
    selected_accessions: set[str],
    project_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    freeze: dict[str, Any] = {
        "path": _relative_or_absolute(path, project_root),
        "present": False,
        "safe_regular_file": False,
        "bytes": 0,
        "sha256": None,
        "schema_version": None,
        "record_count": 0,
        "validation_passed": False,
        "validation_error": None,
        "selected_coverage_count": 0,
        "selected_missing_accessions": sorted(selected_accessions),
    }
    if not _is_safe_regular_file(path):
        freeze["validation_error"] = "missing_or_unsafe_regular_file"
        return freeze, {}
    raw = path.read_bytes()
    freeze.update(
        {
            "present": True,
            "safe_regular_file": True,
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
        }
    )
    try:
        payload = validate_acceptance_index(json.loads(raw.decode("utf-8")))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ) as exc:
        freeze["validation_error"] = type(exc).__name__
        return freeze, {}
    records = {
        record["accession_number"]: record for record in payload["records"]
    }
    missing = selected_accessions - records.keys()
    freeze.update(
        {
            "schema_version": payload["schema_version"],
            "record_count": payload["record_count"],
            "validation_passed": True,
            "validation_error": None,
            "selected_coverage_count": len(selected_accessions) - len(missing),
            "selected_missing_accessions": sorted(missing),
        }
    )
    return freeze, records


def _load_daily_primary_records(
    path: Path,
    *,
    project_root: Path,
    ledger_sha256: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    summary: dict[str, Any] = {
        "path": _relative_or_absolute(path, project_root),
        "present": False,
        "sha256": None,
        "schema_version": None,
        "declared_ledger_sha256": None,
        "ledger_sha256_matches": False,
        "declared_artifact_count": 0,
        "validated_reusable_primary_count": 0,
    }
    if not _is_safe_regular_file(path):
        return summary, {}
    raw = path.read_bytes()
    summary["present"] = True
    summary["sha256"] = sha256_bytes(raw)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return summary, {}
    if not isinstance(payload, dict) or not isinstance(
        payload.get("artifacts"), list
    ):
        return summary, {}
    summary["schema_version"] = payload.get("schema_version")
    summary["declared_ledger_sha256"] = payload.get("ledger_sha256")
    summary["ledger_sha256_matches"] = (
        payload.get("ledger_sha256") == ledger_sha256
    )
    summary["declared_artifact_count"] = len(payload["artifacts"])
    reusable: dict[str, dict[str, Any]] = {}
    for record in payload["artifacts"]:
        if not isinstance(record, dict):
            continue
        accession = str(record.get("accession", ""))
        raw_path = _safe_project_path(record.get("raw_path"), project_root)
        if not accession or raw_path is None:
            continue
        observation = _file_observation(
            raw_path,
            project_root=project_root,
            expected_sha256=record.get("raw_sha256"),
        )
        if (
            observation["hash_verified"]
            and observation["bytes"] > 0
            and observation["bytes"] <= MAX_PRIMARY_BYTES
        ):
            reusable[accession] = {
                "url": record.get("url"),
                "ticker": record.get("ticker"),
                "cik": str(record.get("cik", "")),
                "primary_document": record.get("primary_document"),
                "raw": observation,
                "normalized_path": record.get("normalized_path"),
            }
    summary["validated_reusable_primary_count"] = len(reusable)
    return summary, reusable


def _corpus_source_status(
    row: dict[str, str],
    *,
    corpus_root: Path,
    project_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = filing_paths(corpus_root, row)
    metadata = _read_json_object(paths["metadata"])
    primary_expected = metadata.get("primary_raw_sha256") if metadata else None
    index_expected = metadata.get("index_raw_sha256") if metadata else None
    primary = _file_observation(
        paths["primary"],
        project_root=project_root,
        expected_sha256=primary_expected,
    )
    filing_index = _file_observation(
        paths["index"],
        project_root=project_root,
        expected_sha256=index_expected,
    )
    primary["metadata_identity_verified"] = bool(
        metadata
        and metadata.get("ticker") == row["ticker"]
        and str(metadata.get("cik")) == row["cik"]
        and metadata.get("accession") == row["accession"]
        and metadata.get("primary_url") == row["source_url"]
    )
    filing_index["metadata_identity_verified"] = bool(
        metadata
        and metadata.get("ticker") == row["ticker"]
        and str(metadata.get("cik")) == row["cik"]
        and metadata.get("accession") == row["accession"]
        and metadata.get("index_url") == row["index_url"]
    )
    primary["verified"] = bool(
        primary["hash_verified"] and primary["metadata_identity_verified"]
    )
    filing_index["verified"] = bool(
        filing_index["hash_verified"]
        and filing_index["metadata_identity_verified"]
    )
    return primary, filing_index


def _manifest_collection_status(
    directory: Path,
    *,
    manifest_name: str,
    accession: str,
    artifact_root: Path,
    binding_field: str,
    expected_binding_sha256: str | None,
    project_root: Path,
    row: dict[str, str] | None = None,
    index_raw: bytes | None = None,
    corpus_root: Path | None = None,
) -> dict[str, Any]:
    """Inspect a future hash manifest without treating loose files as complete."""

    manifest_path = directory / manifest_name
    manifest_observation = _file_observation(
        manifest_path, project_root=project_root
    )
    result: dict[str, Any] = {
        "directory": _relative_or_absolute(directory, project_root),
        "manifest": manifest_observation,
        "discovery_complete": False,
        "declared_file_count": 0,
        "verified_file_count": 0,
        "invalid_or_missing_file_count": 0,
        "binding_field": binding_field,
        "expected_binding_sha256": expected_binding_sha256,
        "binding_verified": False,
    }
    payload = _read_json_object(manifest_path)
    if payload is None or payload.get("accession") != accession:
        return result
    if (
        row is not None
        and index_raw is not None
        and corpus_root is not None
        and expected_binding_sha256 is not None
    ):
        strict = validate_exhibit_manifest(
            manifest_path=manifest_path,
            exhibit_directory=directory,
            corpus_root=corpus_root,
            row=row,
            index_raw=index_raw,
            index_sha256=expected_binding_sha256,
        )
        result.update(
            {
                "discovery_complete": strict["discovery_complete"],
                "declared_file_count": strict["declared_file_count"],
                "verified_file_count": strict["verified_file_count"],
                "invalid_or_missing_file_count": strict[
                    "invalid_or_missing_file_count"
                ],
                "binding_verified": strict["binding_verified"],
            }
        )
        return result
    binding_verified = bool(
        expected_binding_sha256
        and payload.get(binding_field) == expected_binding_sha256
    )
    documents = payload.get("documents")
    if not isinstance(documents, list):
        return result
    verified = 0
    invalid = 0
    for document in documents:
        if not isinstance(document, dict):
            invalid += 1
            continue
        relative_path = str(document.get("relative_path", ""))
        try:
            artifact_root_relative = artifact_root.resolve().relative_to(
                project_root.resolve()
            )
        except ValueError:
            invalid += 1
            continue
        candidate = _safe_project_path(
            artifact_root_relative / relative_path, project_root
        )
        if candidate is None:
            invalid += 1
            continue
        observation = _file_observation(
            candidate,
            project_root=project_root,
            expected_sha256=document.get("sha256"),
        )
        try:
            candidate.resolve().relative_to(directory.resolve())
        except ValueError:
            invalid += 1
            continue
        if observation["hash_verified"]:
            verified += 1
        else:
            invalid += 1
    result.update(
        {
            "discovery_complete": bool(
                payload.get("discovery_complete") is True
                and binding_verified
                and invalid == 0
            ),
            "declared_file_count": len(documents),
            "verified_file_count": verified,
            "invalid_or_missing_file_count": invalid,
            "binding_verified": binding_verified,
        }
    )
    return result


def _xbrl_reconciliation_status(
    path: Path,
    *,
    row: dict[str, str],
    expected_primary_sha256: str | None,
    accepted_at_et: str | None,
    primary_raw: bytes | None,
    companyfacts_raw: bytes | None,
    project_root: Path,
) -> dict[str, Any]:
    observation = _file_observation(path, project_root=project_root)
    result: dict[str, Any] = {
        **observation,
        "identity_verified": False,
        "primary_binding_verified": False,
        "future_facts_excluded": False,
        "verified": False,
    }
    payload = _read_json_object(path)
    if payload is None:
        return result
    if (
        expected_primary_sha256 is not None
        and accepted_at_et is not None
        and primary_raw is not None
        and companyfacts_raw is not None
    ):
        strict = validate_xbrl_reconciliation(
            path=path,
            row=row,
            accepted_at_et=accepted_at_et,
            primary_raw=primary_raw,
            companyfacts_raw=companyfacts_raw,
        )
        result.update(strict)
        return result
    identity_verified = bool(
        payload.get("ticker") == row["ticker"]
        and str(payload.get("cik")) == row["cik"]
        and payload.get("accession") == row["accession"]
    )
    primary_binding_verified = bool(
        expected_primary_sha256
        and payload.get("source_primary_sha256")
        == expected_primary_sha256
    )
    future_facts_excluded = payload.get("future_facts_excluded") is True
    result.update(
        {
            "identity_verified": identity_verified,
            "primary_binding_verified": primary_binding_verified,
            "future_facts_excluded": future_facts_excluded,
            "verified": bool(
                observation["present"]
                and identity_verified
                and primary_binding_verified
                and future_facts_excluded
            ),
        }
    )
    return result


def _load_shared_xbrl(
    corpus_root: Path,
    rows: Iterable[dict[str, str]],
    *,
    project_root: Path,
) -> dict[tuple[str, str], dict[str, Any]]:
    statuses: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        identity = (row["ticker"], row["cik"])
        if identity in statuses:
            continue
        paths = companyfacts_paths(corpus_root, row["ticker"])
        strict = validate_companyfacts_snapshot(
            raw_path=paths["raw"],
            metadata_path=paths["metadata"],
            ticker=row["ticker"],
            cik=row["cik"],
        )
        observation = _file_observation(
            paths["raw"],
            project_root=project_root,
            expected_sha256=strict.get("sha256"),
        )
        statuses[identity] = {
            **observation,
            "metadata_identity_verified": strict[
                "metadata_identity_verified"
            ],
            "payload_identity_verified": strict[
                "payload_identity_verified"
            ],
            "verified": strict["verified"],
        }
    return statuses


def _load_submission_snapshots(
    corpus_root: Path,
    rows: Iterable[dict[str, str]],
    *,
    project_root: Path,
) -> dict[tuple[str, str], dict[str, Any]]:
    statuses: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        identity = (row["ticker"], row["cik"])
        if identity in statuses:
            continue
        paths = submission_paths(corpus_root, row["cik"])
        strict = validate_submission_snapshot(
            raw_path=paths["raw"],
            metadata_path=paths["metadata"],
            ticker=row["ticker"],
            cik=row["cik"],
        )
        observation = _file_observation(
            paths["raw"],
            project_root=project_root,
            expected_sha256=strict.get("sha256"),
        )
        statuses[identity] = {
            **observation,
            "metadata_identity_verified": strict[
                "metadata_identity_verified"
            ],
            "payload_identity_verified": strict[
                "payload_identity_verified"
            ],
            "verified": strict["verified"],
        }
    return statuses


def _load_market_sources(
    corpus_root: Path,
    *,
    project_root: Path,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    manifest_path = corpus_root / "manifest.json"
    summary = _file_observation(manifest_path, project_root=project_root)
    sources: dict[str, list[dict[str, Any]]] = {}
    payload = _read_json_object(manifest_path)
    if payload is None or not isinstance(payload.get("market_sources"), list):
        return summary, sources
    try:
        corpus_root_relative = corpus_root.resolve().relative_to(
            project_root.resolve()
        )
    except ValueError:
        return summary, sources
    for record in payload["market_sources"]:
        if not isinstance(record, dict):
            continue
        ticker = str(record.get("ticker", ""))
        raw_path = _safe_project_path(
            (
                corpus_root_relative / str(record.get("relative_path", ""))
            )
            if not Path(str(record.get("relative_path", ""))).is_absolute()
            else "",
            project_root,
        )
        if not ticker or raw_path is None:
            continue
        observation = _file_observation(
            raw_path,
            project_root=project_root,
            expected_sha256=record.get("raw_sha256"),
        )
        if not observation["hash_verified"]:
            continue
        try:
            start = date.fromisoformat(str(record.get("coverage_start", "")))
            end = date.fromisoformat(
                str(record.get("coverage_end_exclusive", ""))
            )
        except ValueError:
            continue
        sources.setdefault(ticker, []).append(
            {
                "coverage_start": start,
                "coverage_end_exclusive": end,
                "raw": observation,
            }
        )
    return summary, sources


def _market_status(
    row: dict[str, str],
    *,
    accepted_at: str | None,
    sources: dict[str, list[dict[str, Any]]],
    corpus_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    required_end: date | None = None
    acceptance_day: date | None = None
    if accepted_at:
        try:
            acceptance_day = datetime.fromisoformat(accepted_at).date()
            required_end = acceptance_day + timedelta(days=21)
        except ValueError:
            acceptance_day = None
            required_end = None
    covering = None
    if acceptance_day is not None and required_end is not None:
        for source in sources.get(row["ticker"], []):
            if (
                source["coverage_start"] <= acceptance_day
                and source["coverage_end_exclusive"] >= required_end
            ):
                covering = source
                break
    observation_path = filing_paths(corpus_root, row)["market_observation"]
    observation = _file_observation(
        observation_path, project_root=project_root
    )
    return {
        "required": True,
        "required_coverage_start": (
            acceptance_day.isoformat() if acceptance_day else None
        ),
        "required_coverage_end_exclusive": (
            required_end.isoformat() if required_end else None
        ),
        "verified_upstream_source_available": covering is not None,
        "upstream_source": covering["raw"] if covering else None,
        "single_bar_observation": observation,
        "missing": covering is None,
    }


def _count_by(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _corpus_bytes(corpus_root: Path) -> int:
    if not corpus_root.is_dir() or corpus_root.is_symlink():
        return 0
    total = 0
    for path in corpus_root.rglob("*"):
        if _is_safe_regular_file(path):
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def _stage_summary(
    records: list[dict[str, Any]],
    *,
    target: int,
    name: str,
) -> dict[str, Any]:
    stage_records = records[:target]
    stage_issuer_count = len(
        {str(int(row["cik"])) for row in stage_records}
    )
    locally_complete = sum(row["locally_complete"] for row in stage_records)
    acceptance_complete = sum(
        row["acceptance"]["present"] for row in stage_records
    )
    output = {
        "stage": name,
        "target_packet_count": target,
        "selected_packet_count": len(stage_records),
        "acceptance_complete_count": acceptance_complete,
        "locally_complete_packet_count": locally_complete,
        "cohort_selectable": len(stage_records) >= target,
        "offline_artifacts_complete": (
            len(stage_records) >= target and locally_complete >= target
        ),
        "provider_calls_authorized": False,
        "promotion_evidence": False,
    }
    if name == "pilot":
        output["purpose"] = (
            "evidence/provenance QA before qualification; never promotion"
        )
        output["readiness_gate_passed"] = output[
            "offline_artifacts_complete"
        ]
    else:
        corpus_mechanics_minimum_met = (
            target >= MINIMUM_REAL_PACKETS
            and len(stage_records) >= MINIMUM_REAL_PACKETS
            and stage_issuer_count >= QUALIFICATION_MINIMUM_ISSUERS
        )
        output.update(
            {
                "purpose": (
                    "corpus-mechanics qualification input; provider quality "
                    "and live-shadow gates remain separate"
                ),
                "minimum_issuer_design_target": (
                    QUALIFICATION_MINIMUM_ISSUERS
                ),
                "selected_issuer_count": stage_issuer_count,
                "issuer_design_target_met": (
                    stage_issuer_count
                    >= QUALIFICATION_MINIMUM_ISSUERS
                ),
                "corpus_mechanics_minimum_met": (
                    corpus_mechanics_minimum_met
                ),
                "readiness_gate_passed": (
                    output["offline_artifacts_complete"]
                    and corpus_mechanics_minimum_met
                ),
            }
        )
    return output


def inventory_replay_readiness(
    *,
    ledger_path: Path = LEDGER_PATH,
    acceptance_index_path: Path = ACCEPTANCE_INDEX_PATH,
    corpus_root: Path = CORPUS_ROOT,
    daily_artifact_index_path: Path = DAILY_ARTIFACT_INDEX_PATH,
    project_root: Path = ROOT,
    target_packet_count: int = MINIMUM_REAL_PACKETS,
    candidate_padding: int = DEFAULT_CANDIDATE_PADDING,
    pilot_packet_count: int = DEFAULT_PILOT_PACKETS,
) -> dict[str, Any]:
    """Return a deterministic, local-only replay readiness inventory."""

    if target_packet_count <= 0:
        raise CorpusError("target packet count must be positive")
    if candidate_padding < 0:
        raise CorpusError("candidate padding must be non-negative")
    if pilot_packet_count <= 0:
        raise CorpusError("pilot packet count must be positive")

    if not _is_safe_regular_file(ledger_path):
        raise CorpusError(f"evidence ledger missing or unsafe: {ledger_path}")
    ledger_raw = ledger_path.read_bytes()
    ledger_sha256 = sha256_bytes(ledger_raw)
    rows = read_ledger(ledger_path)
    items_by_accession = _raw_ledger_items(ledger_path)
    selected = select_candidate_rows(
        rows,
        target_packet_count=target_packet_count,
        candidate_padding=candidate_padding,
    )
    selected_accessions = {row["accession"] for row in selected}
    acceptance_freeze, acceptance_records = _load_acceptance_freeze(
        acceptance_index_path,
        selected_accessions=selected_accessions,
        project_root=project_root,
    )
    daily_summary, daily_primary = _load_daily_primary_records(
        daily_artifact_index_path,
        project_root=project_root,
        ledger_sha256=ledger_sha256,
    )
    manifest_summary, market_sources = _load_market_sources(
        corpus_root, project_root=project_root
    )
    shared_xbrl = _load_shared_xbrl(
        corpus_root, selected, project_root=project_root
    )
    submission_snapshots = _load_submission_snapshots(
        corpus_root, selected, project_root=project_root
    )

    issuer_distribution: Counter[tuple[str, str]] = Counter()
    form_values: list[str] = []
    year_values: list[str] = []
    item_values: list[str] = []
    cohort_freeze_rows: list[dict[str, Any]] = []
    accession_records: list[dict[str, Any]] = []

    for rank, row in enumerate(selected, start=1):
        items = items_by_accession.get(row["accession"], ())
        issuer_distribution[(row["ticker"], row["cik"])] += 1
        form_values.append(row["form"])
        year_values.append(row["filing_date"][:4])
        item_values.extend(items or ("(none_reported)",))
        acceptance = acceptance_records.get(row["accession"])
        accepted_at = acceptance.get("accepted_at") if acceptance else None
        submission_snapshot = submission_snapshots[
            (row["ticker"], row["cik"])
        ]
        cohort_freeze_rows.append(
            {
                "selection_rank": rank,
                "ticker": row["ticker"],
                "cik": row["cik"],
                "accession": row["accession"],
                "form": row["form"],
                "filing_date": row["filing_date"],
                "items": list(items),
                "acceptance_record_sha256": (
                    acceptance.get("record_sha256") if acceptance else None
                ),
            }
        )

        corpus_primary, corpus_index = _corpus_source_status(
            row, corpus_root=corpus_root, project_root=project_root
        )
        reusable_record = daily_primary.get(row["accession"])
        reusable_primary = (
            reusable_record["raw"] if reusable_record else None
        )
        reusable_identity_verified = bool(
            reusable_record
            and reusable_record.get("url") == row["source_url"]
            and reusable_record.get("ticker") == row["ticker"]
            and reusable_record.get("cik") == row["cik"]
            and reusable_record.get("primary_document")
            == row["primary_document"]
        )
        primary_available = bool(
            corpus_primary["verified"]
            or (
                reusable_primary
                and reusable_primary["hash_verified"]
                and reusable_identity_verified
            )
        )
        available_primary_sha256 = (
            corpus_primary["sha256"]
            if corpus_primary["verified"]
            else (
                reusable_primary["sha256"]
                if (
                    reusable_primary
                    and reusable_primary["hash_verified"]
                    and reusable_identity_verified
                )
                else None
            )
        )

        filing_path_map = filing_paths(corpus_root, row)
        filing_directory = filing_path_map["directory"]
        source_metadata = _read_json_object(filing_path_map["metadata"])
        index_raw = (
            filing_path_map["index"].read_bytes()
            if corpus_index["verified"]
            else None
        )
        exhibit_scope = (
            row["form"] in EXHIBIT_DISCOVERY_FORMS or "9.01" in items
        )
        exhibits = _manifest_collection_status(
            filing_directory / "exhibits",
            manifest_name="exhibit_manifest.json",
            accession=row["accession"],
            artifact_root=corpus_root,
            binding_field="source_filing_index_sha256",
            expected_binding_sha256=(
                corpus_index["sha256"]
                if corpus_index["verified"]
                else None
            ),
            project_root=project_root,
            row=row,
            index_raw=index_raw,
            corpus_root=corpus_root,
        )
        exhibits.update(
            {
                "required": exhibit_scope,
                "missing": bool(
                    exhibit_scope and not exhibits["discovery_complete"]
                ),
                "request_count_exact": exhibits["discovery_complete"],
                "estimated_missing_request_lower": (
                    0
                    if exhibits["discovery_complete"]
                    else (
                        1
                        if (
                            exhibit_scope
                            and (
                                "9.01" in items
                                or "2.02" in items
                            )
                        )
                        else 0
                    )
                ),
                "estimated_missing_request_upper": (
                    0
                    if exhibits["discovery_complete"] or not exhibit_scope
                    else MAX_EXHIBITS_PER_ACCESSION_PLANNING
                ),
            }
        )

        xbrl_required = row["form"] in XBRL_FORMS
        xbrl_source = shared_xbrl[(row["ticker"], row["cik"])]
        primary_raw_for_reconciliation: bytes | None = None
        if corpus_primary["verified"]:
            primary_raw_for_reconciliation = filing_path_map[
                "primary"
            ].read_bytes()
        elif (
            reusable_record
            and reusable_primary
            and reusable_primary["hash_verified"]
            and reusable_identity_verified
        ):
            reusable_path = _safe_project_path(
                reusable_primary.get("path"), project_root
            )
            if reusable_path is not None and _is_safe_regular_file(
                reusable_path
            ):
                primary_raw_for_reconciliation = reusable_path.read_bytes()
        companyfacts_raw: bytes | None = None
        if xbrl_source["verified"]:
            companyfacts_raw = companyfacts_paths(
                corpus_root, row["ticker"]
            )["raw"].read_bytes()
        xbrl_reconciliation = _xbrl_reconciliation_status(
            filing_directory / "xbrl_reconciliation.json",
            row=row,
            expected_primary_sha256=available_primary_sha256,
            accepted_at_et=(
                str(source_metadata.get("accepted_at_et"))
                if source_metadata
                and source_metadata.get("accepted_at_et")
                else None
            ),
            primary_raw=primary_raw_for_reconciliation,
            companyfacts_raw=companyfacts_raw,
            project_root=project_root,
        )
        xbrl = {
            "required": xbrl_required,
            "shared_issuer_companyfacts": xbrl_source,
            "verified_shared_source_available": xbrl_source["verified"],
            "accession_reconciliation": xbrl_reconciliation,
            "missing": bool(
                xbrl_required
                and (
                    not xbrl_source["verified"]
                    or not xbrl_reconciliation["verified"]
                )
            ),
            "point_in_time_rule": (
                "current companyfacts may cross-check only; the packet-bound "
                "reconciliation must use the accession primary and exclude "
                "future facts"
            ),
        }
        market = _market_status(
            row,
            accepted_at=accepted_at,
            sources=market_sources,
            corpus_root=corpus_root,
            project_root=project_root,
        )
        missing_artifacts: list[str] = []
        if not primary_available:
            missing_artifacts.append("primary")
        if not corpus_index["verified"]:
            missing_artifacts.append("filing_index")
        if exhibits["missing"]:
            missing_artifacts.append("exhibits")
        if xbrl["missing"]:
            missing_artifacts.append("xbrl")
        if market["missing"]:
            missing_artifacts.append("market")
        if acceptance is None:
            missing_artifacts.append("acceptance_record")
        if not submission_snapshot["verified"]:
            missing_artifacts.append("raw_submission_snapshot")
        accession_records.append(
            {
                "selection_rank": rank,
                "ticker": row["ticker"],
                "cik": row["cik"],
                "accession": row["accession"],
                "form": row["form"],
                "filing_date": row["filing_date"],
                "items": list(items),
                "acceptance": {
                    "present": acceptance is not None,
                    "accepted_at": accepted_at,
                    "record_sha256": (
                        acceptance.get("record_sha256")
                        if acceptance
                        else None
                    ),
                    "raw_submission_snapshot": submission_snapshot,
                },
                "artifacts": {
                    "primary": {
                        "corpus": corpus_primary,
                        "verified_reusable_daily_primary": (
                            reusable_primary
                            if reusable_identity_verified
                            else None
                        ),
                        "reusable_identity_verified": (
                            reusable_identity_verified
                        ),
                        "available_offline": primary_available,
                        "missing_from_corpus": not corpus_primary["verified"],
                        "missing_locally": not primary_available,
                    },
                    "filing_index": {
                        **corpus_index,
                        "required_for_exhibit_discovery": True,
                        "missing": not corpus_index["verified"],
                    },
                    "exhibits": exhibits,
                    "xbrl": xbrl,
                    "market": market,
                },
                "missing_artifacts": missing_artifacts,
                "locally_complete": not missing_artifacts,
            }
        )

    issuer_rows = [
        {"ticker": ticker, "cik": cik, "count": count}
        for (ticker, cik), count in sorted(issuer_distribution.items())
    ]
    missing_counts = Counter(
        missing
        for record in accession_records
        for missing in record["missing_artifacts"]
    )
    corpus_primary_missing = sum(
        record["artifacts"]["primary"]["missing_from_corpus"]
        for record in accession_records
    )
    optimized_primary_missing = sum(
        record["artifacts"]["primary"]["missing_locally"]
        for record in accession_records
    )
    filing_index_missing = missing_counts["filing_index"]
    exhibit_lower = sum(
        record["artifacts"]["exhibits"][
            "estimated_missing_request_lower"
        ]
        for record in accession_records
    )
    exhibit_upper = sum(
        record["artifacts"]["exhibits"][
            "estimated_missing_request_upper"
        ]
        for record in accession_records
    )
    xbrl_missing_issuers = {
        (record["ticker"], record["cik"])
        for record in accession_records
        if record["artifacts"]["xbrl"]["missing"]
    }
    market_missing_tickers = {
        record["ticker"]
        for record in accession_records
        if record["artifacts"]["market"]["missing"]
    }
    acceptance_missing_issuers = {
        (record["ticker"], record["cik"])
        for record in accession_records
        if not record["acceptance"]["present"]
    }
    submission_snapshot_missing_issuers = {
        identity
        for identity, source in submission_snapshots.items()
        if not source["verified"]
    }
    submissions_backfill_requests = len(acceptance_missing_issuers)
    submission_snapshot_requests = len(
        submission_snapshot_missing_issuers
    )

    current_builder_sec_requests = (
        corpus_primary_missing + filing_index_missing
    )
    current_builder_market_requests = len(market_missing_tickers)
    optimized_sec_requests = (
        optimized_primary_missing
        + filing_index_missing
        + submissions_backfill_requests
        + submission_snapshot_requests
        + len(xbrl_missing_issuers)
        + exhibit_lower
    )
    optimized_sec_requests_upper = (
        optimized_primary_missing
        + filing_index_missing
        + submissions_backfill_requests
        + submission_snapshot_requests
        + len(xbrl_missing_issuers)
        + exhibit_upper
    )

    sample_sizes: list[int] = []
    for record in daily_primary.values():
        combined = int(record["raw"]["bytes"])
        normalized = _safe_project_path(
            record.get("normalized_path"), project_root
        )
        if normalized is not None and _is_safe_regular_file(normalized):
            combined += normalized.stat().st_size
        sample_sizes.append(combined)
    typical_primary_and_normalized = (
        round(sum(sample_sizes) / len(sample_sizes))
        if sample_sizes
        else DEFAULT_TYPICAL_PRIMARY_AND_NORMALIZED_BYTES
    )
    selected_count = len(accession_records)
    issuer_count = len(issuer_rows)
    typical_current_total = (
        selected_count
        * (
            typical_primary_and_normalized
            + TYPICAL_INDEX_BYTES
            + PACKET_AND_METADATA_RESERVE_BYTES
        )
        + issuer_count * TYPICAL_MARKET_BYTES_PER_ISSUER
    )
    typical_qualification_total = (
        typical_current_total
        + exhibit_lower * TYPICAL_EXHIBIT_BYTES
        + len(xbrl_missing_issuers) * TYPICAL_XBRL_BYTES_PER_ISSUER
    )
    current_total_hard_cap = (
        selected_count
        * (
            MAX_PRIMARY_BYTES
            + MAX_INDEX_BYTES
            + NORMALIZED_COPY_RESERVE_BYTES
            + PACKET_AND_METADATA_RESERVE_BYTES
        )
        + issuer_count * MAX_MARKET_BYTES
    )
    qualification_planning_upper = (
        current_total_hard_cap
        + exhibit_upper * MAX_EXHIBIT_BYTES_PLANNING
        + len(xbrl_missing_issuers)
        * MAX_XBRL_ISSUER_BYTES_PLANNING
    )
    incremental_current_hard_cap = (
        corpus_primary_missing * MAX_PRIMARY_BYTES
        + filing_index_missing * MAX_INDEX_BYTES
        + optimized_primary_missing * NORMALIZED_COPY_RESERVE_BYTES
        + selected_count * PACKET_AND_METADATA_RESERVE_BYTES
        + len(market_missing_tickers) * MAX_MARKET_BYTES
    )

    pilot = _stage_summary(
        accession_records,
        target=min(pilot_packet_count, target_packet_count),
        name="pilot",
    )
    qualification = _stage_summary(
        accession_records,
        target=target_packet_count,
        name="qualification",
    )
    qualification["promotion_evidence"] = False

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "strictly_read_only_offline_inventory",
        "selection": {
            "policy": SELECTION_POLICY,
            "target_packet_count": target_packet_count,
            "candidate_padding": candidate_padding,
            "selected_candidate_count": selected_count,
            "ledger_distinct_accession_count": len(rows),
            "selected_cohort_sha256": canonical_sha256(
                cohort_freeze_rows
            ),
            "cohort": cohort_freeze_rows,
        },
        "source_freeze": {
            "ledger": {
                "path": _relative_or_absolute(ledger_path, project_root),
                "bytes": len(ledger_raw),
                "sha256": ledger_sha256,
            },
            "acceptance_index": acceptance_freeze,
        },
        "distributions": {
            "issuers": issuer_rows,
            "forms": _count_by(form_values),
            "filing_years": _count_by(year_values),
            "items": _count_by(item_values),
        },
        "local_indexes": {
            "daily_primary_artifact_index": daily_summary,
            "corpus_manifest": manifest_summary,
        },
        "artifact_summary": {
            "selected_accession_count": selected_count,
            "locally_complete_accession_count": sum(
                record["locally_complete"]
                for record in accession_records
            ),
            "missing_by_artifact": dict(sorted(missing_counts.items())),
            "verified_reusable_daily_primary_count": sum(
                bool(
                    record["artifacts"]["primary"][
                        "verified_reusable_daily_primary"
                    ]
                )
                for record in accession_records
            ),
            "exhibit_discovery_incomplete_count": sum(
                record["artifacts"]["exhibits"]["missing"]
                for record in accession_records
            ),
            "xbrl_missing_issuer_count": len(xbrl_missing_issuers),
            "xbrl_reconciliation_missing_accession_count": sum(
                record["artifacts"]["xbrl"]["required"]
                and not record["artifacts"]["xbrl"][
                    "accession_reconciliation"
                ]["verified"]
                for record in accession_records
            ),
            "market_missing_ticker_count": len(market_missing_tickers),
            "raw_submission_snapshot_missing_issuer_count": (
                submission_snapshot_requests
            ),
        },
        "accessions": accession_records,
        "request_estimates": {
            "inventory_requests": 0,
            "current_builder_unchanged": {
                "sec_primary_requests": corpus_primary_missing,
                "sec_filing_index_requests": filing_index_missing,
                "market_ticker_range_requests": (
                    current_builder_market_requests
                ),
                "total_requests": (
                    current_builder_sec_requests
                    + current_builder_market_requests
                ),
                "note": (
                    "does not credit daily-cache reuse and does not acquire "
                    "exhibits or XBRL"
                ),
            },
            "packet_mechanics_with_verified_reuse_and_acceptance_index": {
                "sec_primary_requests": optimized_primary_missing,
                "sec_raw_submission_snapshot_requests": (
                    submission_snapshot_requests
                ),
                "market_ticker_range_requests": len(
                    market_missing_tickers
                ),
                "total_requests": (
                    optimized_primary_missing
                    + submission_snapshot_requests
                    + len(market_missing_tickers)
                ),
                "qualification_complete": False,
                "note": (
                    "preserves raw SEC submissions and reuses the validated "
                    "acceptance index, but omits filing-index attachment "
                    "discovery, exhibits, and XBRL reconciliation"
                ),
            },
            "qualification_acquisition_with_verified_reuse": {
                "sec_submission_backfill_requests": (
                    submissions_backfill_requests
                ),
                "sec_raw_submission_snapshot_requests": (
                    submission_snapshot_requests
                ),
                "sec_primary_requests": optimized_primary_missing,
                "sec_filing_index_requests": filing_index_missing,
                "sec_exhibit_request_lower": exhibit_lower,
                "sec_exhibit_request_upper": exhibit_upper,
                "sec_xbrl_issuer_requests": len(xbrl_missing_issuers),
                "market_ticker_range_requests": len(market_missing_tickers),
                "total_request_lower": (
                    optimized_sec_requests + len(market_missing_tickers)
                ),
                "total_request_upper": (
                    optimized_sec_requests_upper
                    + len(market_missing_tickers)
                ),
                "exhibit_count_exact": exhibit_lower == exhibit_upper,
            },
            "assumptions": {
                "one_primary_request_per_missing_accession": True,
                "one_index_request_per_missing_accession": True,
                "one_xbrl_companyfacts_request_per_missing_issuer": True,
                "one_raw_submissions_request_per_missing_issuer": True,
                "one_market_range_request_per_missing_ticker": True,
                "maximum_exhibits_per_accession_planning_assumption": (
                    MAX_EXHIBITS_PER_ACCESSION_PLANNING
                ),
                "exhibit_range_is_not_a_protocol_hard_limit": True,
            },
        },
        "storage_estimates": {
            "current_corpus_bytes": _corpus_bytes(corpus_root),
            "observed_daily_primary_normalized_sample_count": len(
                sample_sizes
            ),
            "observed_or_default_typical_primary_normalized_bytes": (
                typical_primary_and_normalized
            ),
            "current_builder_typical_projected_total_bytes": (
                typical_current_total
            ),
            "current_builder_projected_total_hard_cap_bytes": (
                current_total_hard_cap
            ),
            "current_builder_incremental_hard_cap_bytes": (
                incremental_current_hard_cap
            ),
            "qualification_typical_projected_total_bytes": (
                typical_qualification_total
            ),
            "qualification_planning_upper_bytes": (
                qualification_planning_upper
            ),
            "qualification_upper_is_planning_not_protocol_bound": True,
            "caps_and_reserves": {
                "primary_bytes": MAX_PRIMARY_BYTES,
                "filing_index_bytes": MAX_INDEX_BYTES,
                "market_ticker_range_bytes": MAX_MARKET_BYTES,
                "normalized_copy_reserve_bytes_per_accession": (
                    NORMALIZED_COPY_RESERVE_BYTES
                ),
                "packet_metadata_reserve_bytes_per_accession": (
                    PACKET_AND_METADATA_RESERVE_BYTES
                ),
                "xbrl_bytes_per_issuer_planning": (
                    MAX_XBRL_ISSUER_BYTES_PLANNING
                ),
                "exhibit_bytes_per_document_planning": (
                    MAX_EXHIBIT_BYTES_PLANNING
                ),
            },
        },
        "stage_readiness": {
            "pilot": pilot,
            "qualification": qualification,
            "distinction": (
                "pilot validates acquisition/evidence mechanics on a small "
                "quarantined sample; qualification uses at least 250 frozen "
                "packets across at least 20 issuers and still cannot substitute "
                "for annotations, provider evaluation, or live shadow"
            ),
        },
        "boundaries": {
            "network_used": False,
            "files_written": False,
            "authentication_requested": False,
            "credentials_read": False,
            "model_used": False,
            "provider_api_used": False,
            "email_used": False,
            "smtp_used": False,
            "broker_used": False,
            "account_read": False,
            "order_code_created": False,
            "canonical_decision_effect": False,
            "live_inference_unlock": False,
        },
    }
    unsigned = dict(report)
    report["inventory_sha256"] = canonical_sha256(unsigned)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print a deterministic, read-only/offline replay readiness "
            "inventory as JSON."
        )
    )
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument(
        "--acceptance-index", type=Path, default=ACCEPTANCE_INDEX_PATH
    )
    parser.add_argument("--corpus-root", type=Path, default=CORPUS_ROOT)
    parser.add_argument(
        "--daily-artifact-index",
        type=Path,
        default=DAILY_ARTIFACT_INDEX_PATH,
    )
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument(
        "--target-packets", type=int, default=MINIMUM_REAL_PACKETS
    )
    parser.add_argument(
        "--candidate-padding", type=int, default=DEFAULT_CANDIDATE_PADDING
    )
    parser.add_argument(
        "--pilot-packets", type=int, default=DEFAULT_PILOT_PACKETS
    )
    parser.add_argument(
        "--require-ready",
        choices=("pilot", "qualification"),
        default=None,
        help=(
            "optional fail-closed exit status; JSON is still printed and no "
            "files are written"
        ),
    )
    args = parser.parse_args()
    try:
        report = inventory_replay_readiness(
            ledger_path=args.ledger,
            acceptance_index_path=args.acceptance_index,
            corpus_root=args.corpus_root,
            daily_artifact_index_path=args.daily_artifact_index,
            project_root=args.project_root,
            target_packet_count=args.target_packets,
            candidate_padding=args.candidate_padding,
            pilot_packet_count=args.pilot_packets,
        )
    except (CorpusError, OSError, UnicodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "inventory_error": type(exc).__name__,
                    "boundaries": {
                        "network_used": False,
                        "files_written": False,
                        "authentication_requested": False,
                    },
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    if args.require_ready:
        ready = report["stage_readiness"][args.require_ready][
            "readiness_gate_passed"
        ]
        return 0 if ready else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
