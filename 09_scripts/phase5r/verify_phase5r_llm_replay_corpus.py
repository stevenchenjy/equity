#!/usr/bin/env python3
"""Offline, read-only verifier for the Phase 5R LLM replay corpus."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date, datetime, time as datetime_time
from pathlib import Path
from typing import Any

from prepare_phase5r_llm_replay_corpus import (
    ADVERSARIAL_MUTATIONS,
    CORPUS_ROOT,
    EASTERN,
    LEDGER_PATH,
    MANIFEST_NAME,
    MANIFEST_SCHEMA_VERSION,
    MAX_INDEX_BYTES,
    MAX_MARKET_BYTES,
    MAX_PRIMARY_BYTES,
    MINIMUM_ADVERSARIAL_SAFETY_PROBES,
    MINIMUM_MATERIAL_TRANSITION_PROBES,
    MINIMUM_REAL_ISSUERS,
    MINIMUM_REAL_PACKETS,
    PACKET_SCHEMA_VERSION,
    SHA256_PATTERN,
    CorpusError,
    canonical_sha256,
    parse_market_history,
    parse_sec_acceptance,
    read_ledger,
    resolve_corpus_path,
    sha256_bytes,
    validate_acceptance_filing_date,
    validate_market_url,
    validate_sec_archive_url,
)
from refresh_phase5r_sec_filing_artifacts import (
    build_chunks,
    normalize_document,
)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise CorpusError(f"{label} is missing or symlinked")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise CorpusError(f"{label} must be a JSON object")
    return payload


def _source_by_type(packet: dict[str, Any], source_type: str) -> dict[str, Any]:
    sources = [
        row
        for row in packet.get("source_catalog", [])
        if isinstance(row, dict) and row.get("source_type") == source_type
    ]
    if len(sources) != 1:
        raise CorpusError(f"packet must contain exactly one {source_type}")
    return sources[0]


def _verified_file(
    corpus_root: Path,
    source: dict[str, Any],
    *,
    label: str,
    max_bytes: int,
) -> tuple[Path, bytes]:
    relative_path = str(source.get("relative_path", ""))
    path = resolve_corpus_path(corpus_root, relative_path)
    if not path.is_file() or path.is_symlink():
        raise CorpusError(f"{label} artifact is missing or symlinked")
    if path.stat().st_size <= 0 or path.stat().st_size > max_bytes:
        raise CorpusError(f"{label} artifact exceeds its size contract")
    content = path.read_bytes()
    digest = str(source.get("raw_sha256", ""))
    if not SHA256_PATTERN.fullmatch(digest) or sha256_bytes(content) != digest:
        raise CorpusError(f"{label} artifact hash mismatch")
    return path, content


def verify_packet(
    packet: dict[str, Any],
    *,
    corpus_root: Path,
    ledger_row: dict[str, str],
    upstream_market: tuple[
        dict[str, Any], dict[date, dict[str, Any]], dict[str, str]
    ],
) -> dict[str, str]:
    if packet.get("schema_version") != PACKET_SCHEMA_VERSION:
        raise CorpusError("packet schema version mismatch")
    stored_packet_id = str(packet.get("packet_id", ""))
    unsigned = dict(packet)
    unsigned.pop("packet_id", None)
    if (
        SHA256_PATTERN.fullmatch(stored_packet_id) is None
        or canonical_sha256(unsigned) != stored_packet_id
    ):
        raise CorpusError("packet ID does not match canonical content")
    for key in ("ticker", "cik", "form", "filing_date", "accession"):
        if packet.get(key) != ledger_row.get(key):
            raise CorpusError(f"packet {key} does not match evidence ledger")

    historical = packet.get("historical_outcome")
    if (
        not isinstance(historical, dict)
        or historical.get("decision_label") is not None
        or historical.get("label_status")
        != "unlabeled_not_available_from_primary_sources"
        or historical.get("must_not_be_inferred_from_future_returns") is not True
    ):
        raise CorpusError("packet fabricates or weakens historical label status")
    evaluation = packet.get("evaluation_status")
    if (
        not isinstance(evaluation, dict)
        or evaluation.get("real_source_packet_validity_only") is not True
        or evaluation.get("provider_quality_scoring_eligible") is not False
        or evaluation.get("requires_separate_reference_annotation") is not True
    ):
        raise CorpusError("packet conflates source validity and provider quality")
    boundaries = packet.get("boundaries")
    if not isinstance(boundaries, dict):
        raise CorpusError("packet boundaries are missing")
    false_boundaries = (
        "email_used",
        "smtp_used",
        "account_read",
        "broker_used",
        "order_code_created",
        "model_used",
        "api_key_used",
        "canonical_decision_effect",
        "live_inference_unlock",
    )
    if any(boundaries.get(key) is not False for key in false_boundaries):
        raise CorpusError("packet contains a prohibited side-effect boundary")

    acceptance = packet.get("acceptance")
    if not isinstance(acceptance, dict):
        raise CorpusError("packet acceptance block is missing")
    try:
        accepted_at = datetime.fromisoformat(
            str(acceptance["accepted_at_et"])
        )
        as_of = datetime.fromisoformat(str(packet["as_of_et"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError("packet timestamps are invalid") from exc
    if (
        accepted_at.tzinfo is None
        or as_of.tzinfo is None
        or as_of <= accepted_at
    ):
        raise CorpusError("packet point-in-time timestamp ordering is invalid")
    validate_acceptance_filing_date(
        accepted_at.isoformat(timespec="seconds"), ledger_row["filing_date"]
    )

    primary = _source_by_type(packet, "sec_primary_document")
    expected_primary_url = validate_sec_archive_url(
        str(primary.get("url", "")),
        cik=ledger_row["cik"],
        accession=ledger_row["accession"],
        expected_filename=ledger_row["primary_document"],
    )
    if expected_primary_url != ledger_row["source_url"]:
        raise CorpusError("packet SEC primary URL differs from evidence ledger")
    _, primary_raw = _verified_file(
        corpus_root,
        primary,
        label="SEC primary",
        max_bytes=MAX_PRIMARY_BYTES,
    )
    if primary.get("authority") != "official_sec_primary":
        raise CorpusError("SEC primary source authority is incorrect")
    if primary.get("accepted_at_et") != acceptance["accepted_at_et"]:
        raise CorpusError("SEC primary acceptance timestamp mismatch")

    index_source = _source_by_type(packet, "sec_filing_index")
    validate_sec_archive_url(
        str(index_source.get("url", "")),
        cik=ledger_row["cik"],
        accession=ledger_row["accession"],
        expected_filename=f"{ledger_row['accession']}-index.html",
    )
    _, index_raw = _verified_file(
        corpus_root,
        index_source,
        label="SEC filing index",
        max_bytes=MAX_INDEX_BYTES,
    )
    parsed_acceptance, parsed_header = parse_sec_acceptance(index_raw)
    if (
        parsed_acceptance != acceptance.get("accepted_at_et")
        or parsed_header != acceptance.get("index_header_value")
        or index_source.get("accepted_at_et") != parsed_acceptance
        or index_source.get("locator", {}).get("header_value") != parsed_header
    ):
        raise CorpusError("SEC index acceptance provenance mismatch")

    derived = packet.get("derived_text")
    if not isinstance(derived, dict):
        raise CorpusError("packet derived-text block is missing")
    normalized_path = resolve_corpus_path(
        corpus_root, str(derived.get("relative_path", ""))
    )
    if not normalized_path.is_file() or normalized_path.is_symlink():
        raise CorpusError("normalized filing text is missing or symlinked")
    normalized_text = normalized_path.read_text(encoding="utf-8")
    expected_normalized = normalize_document(
        primary_raw,
        str(primary.get("content_type", "")),
        str(primary.get("charset", "utf-8")),
    )
    if (
        normalized_text != expected_normalized
        or sha256_bytes(normalized_text.encode("utf-8"))
        != derived.get("normalized_sha256")
        or len(normalized_text) != derived.get("normalized_chars")
        or build_chunks(normalized_text) != derived.get("chunks")
    ):
        raise CorpusError("normalized filing derivation or chunk hashes mismatch")

    market_source = _source_by_type(
        packet, "public_historical_daily_market_data"
    )
    validate_market_url(
        str(market_source.get("url", "")), ticker=ledger_row["ticker"]
    )
    _, observation_raw = _verified_file(
        corpus_root,
        market_source,
        label="market as-of observation",
        max_bytes=64 * 1024,
    )
    try:
        observation = json.loads(observation_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusError("market as-of observation is unreadable") from exc
    if (
        not isinstance(observation, dict)
        or set(observation)
        != {
            "schema_version",
            "ticker",
            "as_of_et",
            "source_url",
            "upstream_raw_sha256",
            "bar",
            "metadata",
            "future_bars_included",
        }
        or observation.get("schema_version")
        != "phase5r_llm_replay_market_observation_v1"
        or observation.get("ticker") != ledger_row["ticker"]
        or observation.get("as_of_et") != packet.get("as_of_et")
        or observation.get("source_url") != market_source.get("url")
        or observation.get("future_bars_included") is not False
        or not isinstance(observation.get("bar"), dict)
        or set(observation["bar"])
        != {"bar_index", "timestamp", "bar_date", "close"}
    ):
        raise CorpusError("market observation contains extra/future or invalid data")
    upstream_source, bars, market_metadata = upstream_market
    if (
        upstream_source.get("ticker") != ledger_row["ticker"]
        or upstream_source.get("url") != market_source.get("url")
        or upstream_source.get("raw_sha256")
        != market_source.get("upstream_raw_sha256")
        or observation.get("upstream_raw_sha256")
        != upstream_source.get("raw_sha256")
    ):
        raise CorpusError("market observation upstream provenance mismatch")
    market_close = packet.get("market_close")
    if not isinstance(market_close, dict):
        raise CorpusError("packet market-close block is missing")
    try:
        bar_date = date.fromisoformat(str(market_close["bar_date"]))
        bar_index = int(market_close["bar_index"])
        close = float(market_close["close"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError("packet market-close values are invalid") from exc
    accepted_et_date = accepted_at.astimezone(EASTERN).date()
    eligible_dates = sorted(day for day in bars if day > accepted_et_date)
    if not eligible_dates or bar_date != eligible_dates[0]:
        raise CorpusError("market close is not first valid date after acceptance")
    expected_bar = bars[bar_date]
    if (
        bar_index != expected_bar["bar_index"]
        or not math.isclose(
            close, float(expected_bar["close"]), rel_tol=0, abs_tol=1e-12
        )
        or market_close.get("complete_close_verified") is not True
        or market_close.get("currency") != market_metadata["currency"]
        or market_close.get("exchange_timezone")
        != market_metadata["exchange_timezone"]
        or observation["bar"] != expected_bar
        or observation.get("metadata")
        != {
            "currency": market_metadata["currency"],
            "exchange_timezone": market_metadata["exchange_timezone"],
            "exchange_name": market_metadata["exchange_name"],
            "authority": market_metadata["data_authority"],
        }
    ):
        raise CorpusError("market-close locator/value provenance mismatch")
    expected_as_of = datetime.combine(
        bar_date, datetime_time(23, 59, 59), tzinfo=EASTERN
    )
    if as_of != expected_as_of:
        raise CorpusError("packet as-of is not end-of-day after verified close")
    locator = market_source.get("locator", {})
    if (
        locator.get("bar_index") != expected_bar["bar_index"]
        or locator.get("timestamp") != expected_bar["timestamp"]
        or market_source.get("available_as_of_et") != packet["as_of_et"]
    ):
        raise CorpusError("market source locator does not match selected bar")

    return {
        "packet_id": stored_packet_id,
        "ticker": ledger_row["ticker"],
        "cik": str(int(ledger_row["cik"])),
        "accession": ledger_row["accession"],
        "accepted_at_et": accepted_at.isoformat(timespec="seconds"),
    }


def _verify_cases(
    cases: Any, packets_by_id: dict[str, dict[str, str]]
) -> tuple[int, int, int]:
    if not isinstance(cases, list):
        raise CorpusError("manifest cases must be a list")
    case_ids: set[str] = set()
    transition_fingerprints: set[str] = set()
    transition_pairs: set[tuple[str, str]] = set()
    transition_count = 0
    adversarial_count = 0
    for case in cases:
        if not isinstance(case, dict):
            raise CorpusError("case must be an object")
        case_id = str(case.get("case_id", ""))
        if not case_id or case_id in case_ids:
            raise CorpusError("case IDs must be non-empty and unique")
        case_ids.add(case_id)
        if (
            case.get("historical_decision_label") is not None
            or case.get("provider_quality_scoring_eligible") is not False
        ):
            raise CorpusError("case fabricates a label or unlocks provider scoring")
        kind = case.get("case_kind")
        if kind == "material_transition_detection_probe":
            prior = packets_by_id.get(str(case.get("prior_packet_id", "")))
            current = packets_by_id.get(str(case.get("current_packet_id", "")))
            if prior is None or current is None:
                raise CorpusError("transition case references an unknown packet")
            identity = {
                "case_kind": kind,
                "ticker": case.get("ticker"),
                "prior_packet_id": case.get("prior_packet_id"),
                "current_packet_id": case.get("current_packet_id"),
            }
            expected_fingerprint = canonical_sha256(identity)
            pair = (
                str(case.get("prior_packet_id", "")),
                str(case.get("current_packet_id", "")),
            )
            if (
                prior["ticker"] != current["ticker"]
                or prior["ticker"] != case.get("ticker")
                or datetime.fromisoformat(prior["accepted_at_et"])
                >= datetime.fromisoformat(current["accepted_at_et"])
                or case.get("ground_truth_status")
                != "unlabeled_requires_reference_annotation"
                or case.get("material_transition_claimed") is not False
                or case.get("transition_fingerprint") != expected_fingerprint
                or expected_fingerprint in transition_fingerprints
                or pair in transition_pairs
            ):
                raise CorpusError("transition probe chronology/label is invalid")
            transition_fingerprints.add(expected_fingerprint)
            transition_pairs.add(pair)
            transition_count += 1
        elif kind == "adversarial_safety_probe":
            if (
                str(case.get("base_packet_id", "")) not in packets_by_id
                or case.get("synthetic_mutation") not in ADVERSARIAL_MUTATIONS
                or case.get("expected_safety_outcome") != "reject_or_abstain"
                or case.get("ground_truth_status")
                != "safety_contract_only_not_market_outcome"
            ):
                raise CorpusError("adversarial safety probe is invalid")
            adversarial_count += 1
        else:
            raise CorpusError("unknown replay evaluation case kind")
    return len(cases), transition_count, adversarial_count


def verify_corpus(
    *,
    corpus_root: Path = CORPUS_ROOT,
    ledger_path: Path = LEDGER_PATH,
    enforce_minimums: bool = True,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    issuer_count = 0
    manifest_path = (
        corpus_root / MANIFEST_NAME
        if manifest_path is None
        else manifest_path
    )
    if not manifest_path.exists():
        return {
            "passed": False,
            "real_packet_count": 0,
            "distinct_issuer_count": 0,
            "case_count": 0,
            "material_transition_probe_count": 0,
            "adversarial_safety_probe_count": 0,
            "real_source_validity_passed": False,
            "provider_quality_scored": False,
            "live_inference_unlock": False,
            "network_used": False,
            "files_written": False,
            "issues": ["manifest_missing"],
        }
    try:
        manifest = _read_json_object(manifest_path, "corpus manifest")
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise CorpusError("manifest schema version mismatch")
        selection = manifest.get("selection")
        if not isinstance(selection, dict):
            raise CorpusError("manifest ledger provenance mismatch")
        ledger_rows = read_ledger(ledger_path)
        ledger_by_accession = {
            row["accession"]: row for row in ledger_rows
        }
        if (
            selection.get("ledger_sha256")
            != sha256_bytes(ledger_path.read_bytes())
            or selection.get("ledger_distinct_accessions") != len(ledger_rows)
        ):
            raise CorpusError("manifest ledger provenance mismatch")
        market_sources = manifest.get("market_sources")
        if not isinstance(market_sources, list):
            raise CorpusError("manifest market sources must be a list")
        upstream_markets: dict[
            str,
            tuple[
                dict[str, Any],
                dict[date, dict[str, Any]],
                dict[str, str],
            ],
        ] = {}
        for source in market_sources:
            if not isinstance(source, dict):
                raise CorpusError("manifest market source must be an object")
            ticker = str(source.get("ticker", ""))
            if not ticker or ticker in upstream_markets:
                raise CorpusError("manifest market tickers must be unique")
            validate_market_url(str(source.get("url", "")), ticker=ticker)
            _, market_raw = _verified_file(
                corpus_root,
                source,
                label="upstream market",
                max_bytes=MAX_MARKET_BYTES,
            )
            bars, market_metadata = parse_market_history(
                market_raw, ticker=ticker
            )
            upstream_markets[ticker] = (source, bars, market_metadata)
        packets = manifest.get("packets")
        if not isinstance(packets, list):
            raise CorpusError("manifest packets must be a list")
        packets_by_id: dict[str, dict[str, str]] = {}
        accessions: set[str] = set()
        ticker_to_cik: dict[str, str] = {}
        for record in packets:
            if not isinstance(record, dict):
                raise CorpusError("manifest packet record must be an object")
            packet_path = resolve_corpus_path(
                corpus_root, str(record.get("relative_path", ""))
            )
            packet_bytes = packet_path.read_bytes()
            if (
                packet_path.is_symlink()
                or sha256_bytes(packet_bytes) != record.get("file_sha256")
            ):
                raise CorpusError("manifest packet file hash mismatch")
            packet = _read_json_object(packet_path, "replay packet")
            accession = str(record.get("accession", ""))
            ledger_row = ledger_by_accession.get(accession)
            if ledger_row is None:
                raise CorpusError("packet accession is absent from ledger")
            upstream_market = upstream_markets.get(ledger_row["ticker"])
            if upstream_market is None:
                raise CorpusError("packet ticker lacks an upstream market source")
            verified = verify_packet(
                packet,
                corpus_root=corpus_root,
                ledger_row=ledger_row,
                upstream_market=upstream_market,
            )
            prior_cik = ticker_to_cik.setdefault(
                verified["ticker"], verified["cik"]
            )
            if prior_cik != verified["cik"]:
                raise CorpusError(
                    "corpus ticker maps to multiple CIK identities"
                )
            if (
                verified["packet_id"] != record.get("packet_id")
                or record.get("historical_label_status")
                != "unlabeled_not_available_from_primary_sources"
                or record.get("provider_quality_scoring_eligible") is not False
                or accession in accessions
                or verified["packet_id"] in packets_by_id
            ):
                raise CorpusError("manifest packet identity/label is invalid")
            accessions.add(accession)
            packets_by_id[verified["packet_id"]] = verified
        (
            case_count,
            transition_case_count,
            adversarial_case_count,
        ) = _verify_cases(manifest.get("cases"), packets_by_id)
        quality = manifest.get("quality_separation")
        if (
            not isinstance(quality, dict)
            or quality.get("real_source_packet_validity_measured") is not True
            or quality.get("provider_quality_scored") is not False
            or quality.get("historical_decision_labels_present") is not False
            or quality.get("future_returns_used_as_labels") is not False
            or quality.get("live_inference_unlock") is not False
            or quality.get("fixture_or_corpus_completion_unlocks_model") is not False
        ):
            raise CorpusError("manifest quality/promotion separation is invalid")
        binding = manifest.get("promotion_binding_contract")
        if (
            not isinstance(binding, dict)
            or binding.get("separate_provider_evaluation_report_required")
            is not True
            or binding.get("evaluation_must_bind_exact_manifest_file_sha256")
            is not True
            or binding.get("evaluation_must_bind_model_registry_file_sha256")
            is not True
            or binding.get(
                "evaluation_must_bind_each_model_identifier_and_config_sha256"
            )
            is not True
            or binding.get("evaluation_must_bind_each_prompt_sha256") is not True
            or binding.get("evaluation_must_bind_provider_response_sha256")
            is not True
            or binding.get("activation_must_fail_without_matching_bound_report")
            is not True
            or binding.get("corpus_or_fixture_counts_unlock_live_shadow")
            is not False
        ):
            raise CorpusError("provider-evaluation hash binding contract is invalid")
        boundaries = manifest.get("boundaries")
        if (
            not isinstance(boundaries, dict)
            or any(value is not False for value in boundaries.values())
        ):
            raise CorpusError("manifest boundary claims are not fail-closed")
        source_policy = manifest.get("source_policy")
        if (
            not isinstance(source_policy, dict)
            or source_policy.get("sec_authority")
            != "official SEC EDGAR filing archives"
            or source_policy.get("acceptance_timestamp_source")
            != "SEC filing-index Accepted field"
            or source_policy.get("market_source_role")
            != "secondary public historical daily close only"
            or source_policy.get("declared_user_agent_used") is not True
            or source_policy.get("sec_rate_limit_at_or_below_two_per_second")
            is not True
            or isinstance(
                source_policy.get("sec_requests_per_second"), bool
            )
            or not isinstance(
                source_policy.get("sec_requests_per_second"), (int, float)
            )
            or not 0
            < float(source_policy["sec_requests_per_second"])
            <= 2.0
        ):
            raise CorpusError("manifest public-source/rate policy is invalid")
        requirements = manifest.get("requirements")
        issuer_count = len(
            {row["cik"] for row in packets_by_id.values()}
        )
        minimums_met = (
            len(packets_by_id) >= MINIMUM_REAL_PACKETS
            and issuer_count >= MINIMUM_REAL_ISSUERS
            and transition_case_count >= MINIMUM_MATERIAL_TRANSITION_PROBES
            and adversarial_case_count >= MINIMUM_ADVERSARIAL_SAFETY_PROBES
        )
        if (
            not isinstance(requirements, dict)
            or requirements.get("minimum_real_point_in_time_packets")
            != MINIMUM_REAL_PACKETS
            or requirements.get("real_packet_count") != len(packets_by_id)
            or requirements.get("minimum_distinct_issuers")
            != MINIMUM_REAL_ISSUERS
            or requirements.get("minimum_material_transition_probes")
            != MINIMUM_MATERIAL_TRANSITION_PROBES
            or requirements.get("minimum_adversarial_safety_probes")
            != MINIMUM_ADVERSARIAL_SAFETY_PROBES
            or requirements.get("minimum_transition_or_adversarial_cases")
            != (
                MINIMUM_MATERIAL_TRANSITION_PROBES
                + MINIMUM_ADVERSARIAL_SAFETY_PROBES
            )
            or requirements.get("distinct_issuer_count") != issuer_count
            or requirements.get("transition_or_adversarial_case_count")
            != case_count
            or requirements.get("material_transition_probe_count")
            != transition_case_count
            or requirements.get("adversarial_safety_probe_count")
            != adversarial_case_count
            or requirements.get("requirements_met") is not minimums_met
        ):
            raise CorpusError("manifest requirement counts are inconsistent")
        if enforce_minimums and not minimums_met:
            raise CorpusError("corpus minimum packet/case thresholds are unmet")
    except (CorpusError, OSError, UnicodeError, ValueError) as exc:
        issues.append(str(exc))
        packet_count = 0
        case_count = 0
        transition_case_count = 0
        adversarial_case_count = 0
        try:
            packet_count = len(manifest.get("packets", []))
            case_count = len(manifest.get("cases", []))
            transition_case_count = sum(
                isinstance(row, dict)
                and row.get("case_kind")
                == "material_transition_detection_probe"
                for row in manifest.get("cases", [])
            )
            adversarial_case_count = sum(
                isinstance(row, dict)
                and row.get("case_kind") == "adversarial_safety_probe"
                for row in manifest.get("cases", [])
            )
        except (NameError, TypeError):
            pass
        return {
            "passed": False,
            "real_packet_count": packet_count,
            "distinct_issuer_count": issuer_count,
            "case_count": case_count,
            "material_transition_probe_count": transition_case_count,
            "adversarial_safety_probe_count": adversarial_case_count,
            "real_source_validity_passed": False,
            "provider_quality_scored": False,
            "live_inference_unlock": False,
            "network_used": False,
            "files_written": False,
            "issues": issues,
        }
    return {
        "passed": True,
        "real_packet_count": len(packets_by_id),
        "distinct_issuer_count": issuer_count,
        "case_count": case_count,
        "material_transition_probe_count": transition_case_count,
        "adversarial_safety_probe_count": adversarial_case_count,
        "real_source_validity_passed": True,
        "provider_quality_scored": False,
        "live_inference_unlock": False,
        "network_used": False,
        "files_written": False,
        "issues": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--corpus-root", type=Path, default=CORPUS_ROOT)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    del args.check
    report = verify_corpus(
        corpus_root=args.corpus_root,
        ledger_path=args.ledger,
        enforce_minimums=not args.allow_incomplete,
    )
    print(
        f"replay_corpus_verification={'passed' if report['passed'] else 'failed'} "
        f"real_packets={report['real_packet_count']} "
        f"issuers={report['distinct_issuer_count']} "
        f"transition_cases={report['material_transition_probe_count']} "
        f"adversarial_cases={report['adversarial_safety_probe_count']} "
        f"cases={report['case_count']} "
        f"issues={len(report['issues'])} "
        "network_used=false files_written=false provider_quality_scored=false "
        "email_used=false smtp_used=false account_read=false broker_used=false "
        "order_code_created=false model_used=false api_key_used=false "
        "live_inference_unlock=false"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
