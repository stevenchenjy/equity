"""Maintained, source-bound company research. Offline; never an order authority.

A reviewed business case and a reviewed valuation are independent assertions.
The ledger preserves authored conclusions; daily evaluation may reopen a review
but cannot rewrite it, promote conviction, or manufacture a new conclusion.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from daily_common import canonical_sha256, read_json
from sec_acceptance import load_immutable_acceptance_index
from sec_acceptance_extensions import load_extension_artifacts

STORE_REL = Path("04_research/company_research/thesis_dossiers.local.json")
SCHEMA = "maintained_company_theses_v1"
RECORD_SCHEMA = "maintained_company_thesis_review_v1"
INDEX_REL = Path("03_source_data/equity_research/sec_filing_artifact_index.json")
ACCEPTANCE_REL = Path("03_source_data/equity_research/sec_submission_acceptance_index.json")
EXTENSIONS_REL = Path("03_source_data/equity_research/sec_acceptance_extensions")
STATES = {"evidence_incomplete", "reviewed", "monitor", "invalidated"}
BUSINESS_STATES = {"provisionally_supported", "mixed", "challenged", "rejected", "unresolved"}
SECTIONS = ("business_case", "per_share_economics", "valuation", "portfolio_role_and_alternatives")
RECORD_FIELDS = {
    "schema_version", "ticker", "version", "review_id", "reviewed_at", "reviewer",
    "review_state", "financial_period_end", "next_review_at", "change_reason",
    "supersedes_sha256", "sources", "claims", "business_case", "per_share_economics",
    "valuation", "portfolio_role_and_alternatives", "conclusion", "unresolved_questions",
    "invalidation_conditions", "reviewed_material_accessions", "valuation_model", "record_sha256",
}
OPTIONAL_RECORD_FIELDS = {"reviewed_news_events", "reviewed_material_filings"}
FILING_RECEIPT_FIELDS = {"source_id", "ticker", "accession", "url", "normalized_path", "normalized_sha256",
                       "raw_path", "raw_sha256", "fetched_at", "form", "primary_document", "published_at"}
PERIODIC_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}


class ThesisValidationError(ValueError):
    """The review cannot be used as a current maintained conclusion."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ThesisValidationError(message)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ThesisValidationError("review timestamp is invalid") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "review timestamp requires timezone")
    return parsed


def _day(value: Any) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ThesisValidationError("financial period is invalid") from exc


def _inside(root: Path, relative: str) -> Path:
    _require(isinstance(relative, str) and not Path(relative).is_absolute(), "source path must be relative")
    path = (root / relative).resolve()
    _require(path.is_relative_to(root.resolve()) and ".." not in Path(relative).parts, "source path escapes evidence root")
    return path


class _DocumentPeriod(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.capture = False
        self.values: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "ix:nonnumeric":
            self.capture = dict(attrs).get("name", "").lower() == "dei:documentperiodenddate"
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "ix:nonnumeric":
            if self.capture:
                text = " ".join("".join(self.parts).split())
                for fmt in ("%Y-%m-%d", "%B %d, %Y"):
                    try:
                        self.values.append(datetime.strptime(text, fmt).date().isoformat())
                        break
                    except ValueError:
                        continue
            self.capture = False


def evidence_context(root: Path) -> dict[str, Any]:
    """Validate the retained official acceptance chain once per report."""
    index_path = root / ACCEPTANCE_REL
    accepted = load_immutable_acceptance_index(index_path)
    extensions = load_extension_artifacts(
        historical_index_sha256=hashlib.sha256(index_path.read_bytes()).hexdigest(),
        directory=root / EXTENSIONS_REL,
    )
    records = list(accepted["records"])
    records += [row for extension in extensions for row in extension["records"]]
    artifact_index = read_json(root / INDEX_REL, {})
    return {"acceptance": {row["accession_number"]: row for row in records},
            "artifacts": {row["source_id"]: row for row in artifact_index.get("artifacts", [])}}


def source_receipt(artifact: dict[str, Any], context: dict[str, Any], period: str) -> dict[str, Any]:
    """Build a review reference from an existing cached primary filing."""
    accepted = context["acceptance"][artifact["accession"]]
    return {key: artifact[key] for key in (
        "source_id", "ticker", "accession", "url", "normalized_path", "normalized_sha256",
        "raw_path", "raw_sha256", "fetched_at", "form", "primary_document",
    )} | {"published_at": accepted["accepted_at"], "financial_period_end": period}


def _validate_filing_bytes(source: dict[str, Any], ticker: str, reviewed_at: datetime,
                           root: Path, context: dict[str, Any], *, admission: bool = False) -> str:
    """Common retained filing provenance, without assigning a financial period."""
    _require(source["ticker"] == ticker, "source ticker differs")
    accession = source["accession"]
    accepted = context.get("acceptance", {}).get(accession, {})
    _require(accepted.get("ticker") == ticker, "source lacks official acceptance identity")
    published, retrieved = _timestamp(source["published_at"]), _timestamp(source["fetched_at"])
    _require(published == _timestamp(accepted.get("accepted_at")), "source publication timestamp differs")
    _require(published <= retrieved <= reviewed_at, "source retrieved/published after review")
    url = urlsplit(source["url"])
    _require(url.scheme == "https" and url.netloc in {"sec.gov", "www.sec.gov"}
             and not url.query and not url.fragment, "source must be an official SEC document")
    expected_path = f"/Archives/edgar/data/{int(accepted['cik'])}/{accession.replace('-', '')}/{source['primary_document']}"
    _require(url.path == expected_path, "source URL and accession differ")
    prefix = f"02_filings/issuer_filings/{ticker}/{accession}/"
    for path_key, hash_key in (("normalized_path", "normalized_sha256"), ("raw_path", "raw_sha256")):
        _require(source[path_key].startswith(prefix), "source path and identity differ")
        payload = _inside(root, source[path_key]).read_bytes()
        _require(hashlib.sha256(payload).hexdigest() == source[hash_key], "source content hash differs")
    active_artifact = context.get("artifacts", {}).get(source["source_id"])
    if admission:
        _require(active_artifact is not None, "new review source is not in verified artifact index")
    if active_artifact is not None:
        for key in ("ticker", "accession", "url", "normalized_path", "normalized_sha256", "raw_path", "raw_sha256", "form", "primary_document"):
            _require(source[key] == active_artifact.get(key), f"source index differs: {key}")
    # The index selects current documents and may rotate old ones out. Retained
    # bytes and the immutable acceptance chain keep historical reviews auditable.
    return _inside(root, source["normalized_path"]).read_text(encoding="utf-8")


def validate_source(source: dict[str, Any], ticker: str, reviewed_at: datetime,
                    root: Path, context: dict[str, Any], *, admission: bool = False) -> str:
    """Periodic company claims retain the strict financial-period contract."""
    _require(isinstance(source, dict) and set(source) == FILING_RECEIPT_FIELDS | {"financial_period_end"}, "source receipt fields differ")
    _require(source["form"] in PERIODIC_FORMS, "company thesis source requires periodic filing")
    text = _validate_filing_bytes(source, ticker, reviewed_at, root, context, admission=admission)
    _require(_day(source["financial_period_end"]) <= _timestamp(source["published_at"]).date(), "financial period follows publication")
    parsed = _DocumentPeriod()
    parsed.feed(_inside(root, source["raw_path"]).read_text(encoding="utf-8"))
    _require(set(parsed.values) == {source["financial_period_end"]}, "source financial period differs from filing")
    return text


def material_filing_receipt(artifact: dict[str, Any], context: dict[str, Any], *, assessment: str,
                            disposition: str, char_start: int, char_end: int, excerpt: str) -> dict[str, Any]:
    """Bind nonperiodic material-event triage to retained primary-document bytes."""
    source = {key: artifact[key] for key in FILING_RECEIPT_FIELDS - {"published_at"}}
    source["published_at"] = context["acceptance"][artifact["accession"]]["accepted_at"]
    return source | {"assessment": assessment, "disposition": disposition,
                     "citation": {"char_start": char_start, "char_end": char_end, "excerpt": excerpt}}


def validate_material_filings(record: dict[str, Any], root: Path, context: dict[str, Any], *, admission: bool) -> None:
    receipts = record.get("reviewed_material_filings", [])
    _require(isinstance(receipts, list), "material filing receipts must be a list")
    seen = set()
    for receipt in receipts:
        _require(isinstance(receipt, dict) and set(receipt) == FILING_RECEIPT_FIELDS | {"assessment", "disposition", "citation"},
                 "material filing receipt fields differ")
        _require(_text(receipt["form"]) and receipt["form"] not in PERIODIC_FORMS, "material receipt must be a nonperiodic filing")
        _require(_text(receipt["assessment"]) and receipt["disposition"] in {"no_change_to_maintained_view", "reassessment_required"},
                 "material filing assessment or disposition invalid")
        _require(receipt["accession"] not in seen and receipt["accession"] in record["reviewed_material_accessions"],
                 "material filing receipt identity duplicated or unacknowledged")
        text = _validate_filing_bytes(receipt, record["ticker"], _timestamp(record["reviewed_at"]), root, context, admission=admission)
        # The immutable acceptance chain independently verifies nonperiodic form
        # after the rolling artifact index no longer includes this document.
        accepted = context["acceptance"][receipt["accession"]]
        _require(accepted.get("form") == receipt["form"],
                 "material filing identity differs from official acceptance")
        citation = receipt["citation"]
        _require(isinstance(citation, dict) and set(citation) == {"char_start", "char_end", "excerpt"}, "material citation fields differ")
        start, end = citation["char_start"], citation["char_end"]
        _require(type(start) is int and type(end) is int and 0 <= start < end <= len(text), "material citation offsets invalid")
        _require(isinstance(citation["excerpt"], str) and 10 <= len(citation["excerpt"]) <= 1600
                 and text[start:end] == citation["excerpt"], "material citation differs from saved filing")
        seen.add(receipt["accession"])


def verified_reviewed_accessions(record: dict[str, Any]) -> set[str]:
    """Call only after full review validation; a bare accession is not a review."""
    return {source["accession"] for source in record["sources"]} | {
        receipt["accession"] for receipt in record.get("reviewed_material_filings", [])}


def seal_review(record: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(record)
    result.pop("record_sha256", None)
    return result | {"record_sha256": canonical_sha256(result)}


def stable_news_event(event: dict[str, Any]) -> dict[str, Any]:
    """Authored event semantics, excluding discovery/fetch clocks and flags."""
    keys = ("event_id", "source_id", "ticker", "source_type", "title", "url", "published_at")
    result = {key: event.get(key, "") for key in keys}
    if result["published_at"]:
        result["published_at"] = _timestamp(result["published_at"]).astimezone(timezone.utc).isoformat()
    return result


def substantive_news(event: dict[str, Any]) -> bool:
    """Conservative triage only, never a positive/negative business signal."""
    title = str(event.get("title", ""))
    calendar_only = re.search(
        r"\b(?:to|will)\s+(?:participate|present)\b.*\b(?:conference|summit)\b|"
        r"\bannounces?\s+(?:the\s+)?(?:date|timing)\b.*\b(?:earnings|financial results)\b",
        title, re.IGNORECASE)
    return not bool(calendar_only)


def apply_issuer_news_review(view: dict[str, Any], *, ticker: str,
                            news: dict[str, Any], current: datetime) -> None:
    """Keep filing assessment intact while explicitly tracking news triage."""
    record = view.get("review_record") or {}
    reviewed = datetime.fromisoformat(record["reviewed_at"].replace("Z", "+00:00")) if record else None
    acknowledgments = {event_id: set(hashes) for event_id, hashes in news.get("reviewed_event_hashes", {}).items()}
    for receipt in record.get("reviewed_news_events", []):
        acknowledgments.setdefault(receipt["event"]["event_id"], set()).add(receipt["event_sha256"])
    pending, acknowledged, new = [], [], []
    for event in news.get("review_events", news.get("recent_events", [])):
        if event.get("ticker") != ticker or event.get("source_type") != "official_issuer_announcement" or not substantive_news(event):
            continue
        stable = stable_news_event(event)
        published = datetime.fromisoformat(stable["published_at"])
        if published > current:
            continue
        digest = canonical_sha256(stable)
        if digest in acknowledgments.get(stable["event_id"], set()):
            acknowledged.append(stable["event_id"])
            continue
        after_review = reviewed is not None and published > reviewed
        corrected = stable["event_id"] in acknowledgments
        # Loss of feed freshness cannot undo an already verified event. Its
        # exact pending state survives both ageing and later unrelated reviews.
        fresh = event.get("source_fresh") is True or event.get("source_verified_at_admission") is True
        required = digest in news.get("reassessment_event_hashes", {}).get(stable["event_id"], [])
        reason = "reviewed_news_content_changed" if corrected and fresh else "new_material_news_after_review" if (after_review or required) and fresh else "preexisting_news_not_acknowledged" if not after_review else "new_news_source_freshness_unresolved"
        pending.append({**stable, "event_sha256": digest, "reason": reason})
        if (after_review or corrected or required) and fresh:
            new.append(stable["event_id"])
    issuer_sources = [row for row in news.get("sources", []) if row.get("ticker") == ticker]
    view["news_review"] = {
        "status": "pending_new_material_news" if new else "pending_prior_news" if pending else "current",
        "review_scope": "issuer_headline_triage_separate_from_filing_business_view",
        "pending_events": sorted(pending, key=lambda row: (row["published_at"], row["event_id"])),
        "reviewed_event_ids": sorted(acknowledged),
        "coverage_complete": bool(issuer_sources) and all(row.get("freshness") == "fresh" for row in issuer_sources),
        "investment_signal": False,
    }
    if new and view.get("status") in {"reviewed", "monitor", "reassess"}:
        view["status"] = "reassess"
        view["reopen_reasons"] = sorted(set(view.get("reopen_reasons", []) +
            ["new_official_issuer_news_unreviewed:"+event_id for event_id in new]))


def validate_news_reviews(record: dict[str, Any], root: Path, observed_at: str, *, admission: bool) -> None:
    """A headline triage receipt cannot claim the full article was researched."""
    receipts = record.get("reviewed_news_events", [])
    _require(isinstance(receipts, list), "reviewed news receipts must be a list")
    if not receipts:
        return
    current = {}
    if admission:
        from official_news import read_official_news_status
        current = read_official_news_status(now=_timestamp(observed_at),
            manifest_path=root / "01_policies/official_news_sources.json",
            status_path=root / "03_source_data/equity_research/official_news_status.local.json",
            events_path=root / "03_source_data/equity_research/official_news_events.local.json")
    known = {}
    if admission:
        from issuer_news_queue import retained_verified_events
        known.update(retained_verified_events(root, current=_timestamp(observed_at)))
    for event in current.get("recent_events", []):
        if event.get("source_fresh") is True or event["event_id"] not in known:
            known[event["event_id"]] = event
    seen = set()
    for receipt in receipts:
        _require(isinstance(receipt, dict) and set(receipt) == {"event", "event_sha256", "assessment", "review_scope"}, "news review receipt fields differ")
        event = receipt["event"]
        _require(isinstance(event, dict) and set(event) == set(stable_news_event({})), "news review event fields differ")
        _require(event == stable_news_event(event) and receipt["event_sha256"] == canonical_sha256(event), "news review event hash differs")
        _require(event["ticker"] == record["ticker"] and event["source_type"] == "official_issuer_announcement", "news review issuer/source differs")
        _require(event["event_id"] not in seen and _text(event["event_id"]) and _text(receipt["assessment"]), "news review identity or assessment missing")
        _require(receipt["review_scope"] == "issuer_headline_triage", "news review must state headline-only scope")
        _require(_timestamp(event["published_at"]) <= _timestamp(record["reviewed_at"]), "news review predates publication")
        observed = known.get(event["event_id"])
        if admission:
            _require(observed is not None and (observed.get("source_fresh") is True
                or observed.get("source_verified_at_admission") is True), "new news review requires verified fresh issuer event or retained source-bound event")
        # Retain the exact event reviewed even if the issuer later changes its
        # headline. The daily overlay reopens that change without erasing the
        # independently supported filing conclusion.
        if admission:
            _require(stable_news_event(observed) == event, "reviewed news content changed")
        seen.add(event["event_id"])


def validate_review(record: dict[str, Any], root: Path, context: dict[str, Any],
                    observed_at: str, *, admission: bool = False) -> None:
    _require(isinstance(record, dict) and RECORD_FIELDS <= set(record) <= RECORD_FIELDS | OPTIONAL_RECORD_FIELDS, "review fields differ")
    _require(record["schema_version"] == RECORD_SCHEMA, "unsupported review schema")
    _require(seal_review(record) == record, "review hash differs")
    _require(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", str(record["ticker"])) is not None, "invalid review ticker")
    _require(type(record["version"]) is int and record["version"] >= 1, "invalid review version")
    for key in ("review_id", "reviewer", "change_reason", "conclusion"):
        _require(_text(record[key]), f"missing {key}")
    reviewed, due, now = map(_timestamp, (record["reviewed_at"], record["next_review_at"], observed_at))
    _require(reviewed <= now and 0 < (due-reviewed).total_seconds() <= 31*86400, "review window invalid or beyond 31 days")
    _require(record["review_state"] in STATES, "invalid review state")
    _require(isinstance(record["sources"], list) and record["sources"], "review sources missing")
    texts, sources = {}, {}
    for source in record["sources"]:
        text = validate_source(source, record["ticker"], reviewed, root, context, admission=admission)
        source_id = source["source_id"]
        _require(source_id not in sources, "duplicate source identity")
        texts[source_id], sources[source_id] = text, source
    _require(record["financial_period_end"] == max(row["financial_period_end"] for row in sources.values()), "review period does not match latest incorporated source")
    _require(isinstance(record["claims"], list) and record["claims"], "review claims missing")
    claims = {}
    for claim in record["claims"]:
        _require(isinstance(claim, dict) and set(claim) == {"claim_id", "statement", "kind", "stance", "citations"}, "claim fields differ")
        _require(_text(claim["claim_id"]) and claim["claim_id"] not in claims and _text(claim["statement"]), "claim identity/text invalid")
        _require(claim["kind"] in {"reported_fact", "analyst_inference"}, "claim type must separate facts from inference")
        _require(claim["stance"] in {"supporting", "contradictory", "context"}, "claim stance invalid")
        _require(isinstance(claim["citations"], list) and claim["citations"], "claim citation missing")
        for citation in claim["citations"]:
            _require(isinstance(citation, dict) and set(citation) == {"source_id", "char_start", "char_end", "excerpt"}, "citation fields differ")
            source_text = texts.get(citation["source_id"])
            start, end = citation["char_start"], citation["char_end"]
            _require(source_text is not None and type(start) is int and type(end) is int and 0 <= start < end <= len(source_text), "citation offsets invalid")
            _require(10 <= len(citation["excerpt"]) <= 1200 and source_text[start:end] == citation["excerpt"], "citation excerpt differs from saved source")
        claims[claim["claim_id"]] = claim
    for section in SECTIONS:
        item = record[section]
        _require(isinstance(item, dict) and set(item) == {"status", "summary", "claim_ids", "unresolved"}, f"{section} fields differ")
        _require(_text(item["summary"]), f"{section} has no maintained assessment")
        _require(isinstance(item["claim_ids"], list) and item["claim_ids"] and all(key in claims for key in item["claim_ids"]), f"{section} claims missing")
        _require(isinstance(item["unresolved"], list) and all(_text(value) for value in item["unresolved"]), f"{section} unresolved list invalid")
    _require(record["business_case"]["status"] in BUSINESS_STATES, "business case status invalid")
    _require(record["per_share_economics"]["status"] in {"reviewed", "partial", "unresolved"}, "economics status invalid")
    _require(record["valuation"]["status"] in {"unresolved", "reviewed_scenarios"}, "valuation status invalid")
    _require(record["portfolio_role_and_alternatives"]["status"] in {"reviewed", "partial", "unresolved"}, "alternatives status invalid")
    if record["valuation"]["status"] == "unresolved":
        _require(bool(record["valuation"]["unresolved"]), "unresolved valuation requires named gaps")
        _require(record["valuation_model"] is None, "unresolved valuation cannot attach a completed model")
    if record["valuation"]["status"] == "reviewed_scenarios":
        # Reuse the existing source-bound valuation contract, but require an
        # explicit company review of assumptions rather than a generic grid.
        from valuation_input_bundle import validate_and_materialize_bundle
        model = record["valuation_model"]
        fields = {"relative_path", "sha256", "assumptions_reason", "countercase_reason", "claim_ids"}
        _require(isinstance(model, dict) and set(model) == fields, "valuation model receipt missing")
        _require(model["relative_path"].startswith("04_data/equity_research/"), "valuation model path outside approved directory")
        payload = _inside(root, model["relative_path"]).read_bytes()
        _require(hashlib.sha256(payload).hexdigest() == model["sha256"], "valuation model changed after review")
        bundle = json.loads(payload)
        receipts, _ = validate_and_materialize_bundle(bundle, packet_as_of=record["reviewed_at"],
            active_tickers={record["ticker"]}, project_root=root)
        _require(len(receipts) == 1 and receipts[0]["sufficiency"]["valuation_sufficient"], "valuation observations incomplete")
        inputs = next(row for row in bundle["records"] if row["ticker"] == record["ticker"])
        source_by = {row["source_id"]: row for row in inputs["sources"]}
        for key in ("diluted_shares", "cash_and_equivalents", "total_debt", "revenue_ttm", "free_cash_flow_ttm"):
            periods = re.findall(r"\d{4}-\d{2}-\d{2}", inputs["inputs"][key]["period"])
            _require(bool(periods) and max(periods) == record["financial_period_end"], "valuation model financial periods not aligned")
        price_dates = re.findall(r"\d{4}-\d{2}-\d{2}", inputs["inputs"]["share_price"]["period"])
        _require(len(price_dates) == 1 and 0 <= (reviewed.date()-_day(price_dates[0])).days <= 7,
                 "valuation price observation stale at review")
        for key in ("target_price_assumption", "downside_price_assumption"):
            assumption = inputs["inputs"].get(key, {})
            ids = assumption.get("source_ids", [])
            _require(bool(ids) and all(source_by[sid]["source_type"] == "human_valuation_scenario" for sid in ids),
                     "company valuation needs reviewed scenario sources, not generic policy assumptions")
        _require(all(_text(model[key]) for key in ("assumptions_reason", "countercase_reason")), "valuation rationale incomplete")
        _require(isinstance(model["claim_ids"], list) and model["claim_ids"] and all(key in claims for key in model["claim_ids"]), "valuation claim support missing")
    for field in ("unresolved_questions", "invalidation_conditions"):
        _require(isinstance(record[field], list) and record[field] and all(_text(v) for v in record[field]), f"{field} missing")
    stances = {row["stance"] for row in claims.values()}
    _require({"supporting", "contradictory"} <= stances, "review must examine support and counterevidence")
    _require(isinstance(record["reviewed_material_accessions"], list) and record["reviewed_material_accessions"], "reviewed material identities missing")
    for accession in record["reviewed_material_accessions"]:
        accepted = context["acceptance"].get(accession, {})
        _require(accepted.get("ticker") == record["ticker"] and _timestamp(accepted.get("accepted_at")) <= reviewed,
                 "reviewed material accession is unverified or future")
    _require({source["accession"] for source in sources.values()} <= set(record["reviewed_material_accessions"]), "cited filing not acknowledged as incorporated")
    validate_material_filings(record, root, context, admission=admission)
    if admission:
        _require(set(record["reviewed_material_accessions"]) <= verified_reviewed_accessions(record),
                 "acknowledged material filing lacks verified receipt")
    if record["review_state"] == "invalidated":
        _require(record["business_case"]["status"] in {"challenged", "rejected"}, "invalidated view requires negative assessed case")
    if record["review_state"] in {"reviewed", "monitor"}:
        _require(record["business_case"]["status"] != "unresolved", "reviewed view lacks business conclusion")
    validate_news_reviews(record, root, observed_at, admission=admission)


def validate_store(store: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate append-only identities before choosing the latest version."""
    _require(isinstance(store, dict) and set(store) == {"schema_version", "records"} and store["schema_version"] == SCHEMA, "unsupported thesis store")
    _require(isinstance(store["records"], list), "thesis records must be a list")
    latest, ids = {}, set()
    for record in store["records"]:
        _require(isinstance(record, dict) and RECORD_FIELDS <= set(record) <= RECORD_FIELDS | OPTIONAL_RECORD_FIELDS and seal_review(record) == record, "historical review hash or fields invalid")
        ticker = record["ticker"]
        prior = latest.get(ticker)
        _require(type(record["version"]) is int and record["version"] == (prior["version"]+1 if prior else 1), "thesis versions are not contiguous")
        _require(record["supersedes_sha256"] == (prior["record_sha256"] if prior else ""), "thesis supersession chain differs")
        _require(record["review_id"] not in ids, "duplicate review ID")
        _require(not prior or _timestamp(record["reviewed_at"]) >= _timestamp(prior["reviewed_at"]), "review chronology regressed")
        ids.add(record["review_id"])
        latest[ticker] = record
    return latest


def append_review(store: dict[str, Any], record: dict[str, Any], root: Path, observed_at: str) -> dict[str, Any]:
    """Return a new ledger; reject stale writer versions and invalid evidence."""
    validate_store(store)
    new = deepcopy(store)
    new["records"].append(record)
    validate_store(new)
    validate_review(record, root, evidence_context(root), observed_at, admission=True)
    return new


def evaluate_thesis(store: dict[str, Any] | None, ticker: str, observed_at: str,
                    evidence_root: Path | None, *, context: dict[str, Any] | None = None,
                    material_events: list[dict[str, Any]] | None = None,
                    incorporation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Expose authored review and effective freshness without mutating history."""
    result: dict[str, Any] = {"status": "unresolved", "validation_errors": [], "reopen_reasons": [],
        "business_case_status": "unresolved", "valuation_readiness": "unresolved", "conclusion": "",
        "thesis_id": "company_thesis:"+ticker, "thesis_version": None,
        "review_id": "", "version": None, "reviewed_at": "", "next_review_at": "",
        "review_record_sha256": "", "review_record": None, "investment_conviction": "not_assessed",
        "recommendation_authority": False, "automatic_action_allowed": False}
    if store is None:
        result["reopen_reasons"] = ["company_review_not_recorded"]
        return result
    try:
        record = validate_store(store).get(ticker)
        if record is None:
            result["reopen_reasons"] = ["company_review_not_recorded"]
            return result
        _require(evidence_root is not None, "source verification root missing")
        context = context if context is not None else evidence_context(evidence_root)
        validate_review(record, evidence_root, context, observed_at)
        now, reviewed = _timestamp(observed_at), _timestamp(record["reviewed_at"])
        result.update({"review_record": deepcopy(record), "review_id": record["review_id"], "version": record["version"],
            "thesis_version": record["version"],
            "reviewed_at": record["reviewed_at"], "next_review_at": record["next_review_at"],
            "review_record_sha256": record["record_sha256"], "conclusion": record["conclusion"],
            "business_case_status": record["business_case"]["status"], "valuation_readiness": record["valuation"]["status"],
            "status": record["review_state"]})
        reviewed_accessions = verified_reviewed_accessions(record)
        reasons = ["material_filing_acknowledgment_without_verified_receipt:"+accession
                   for accession in set(record["reviewed_material_accessions"]) - reviewed_accessions]
        reasons += ["reviewed_material_filing_requires_reassessment:"+receipt["accession"]
                    for receipt in record.get("reviewed_material_filings", [])
                    if receipt["disposition"] == "reassessment_required"]
        if now >= _timestamp(record["next_review_at"]):
            reasons.append("scheduled_company_review_due")
        if incorporation is None or incorporation.get("status") != "incorporated":
            reasons.append("latest_earnings_pending_incorporation")
        else:
            if incorporation.get("latest_report_period_end", "") > record["financial_period_end"]:
                reasons.append("new_financial_period_not_reviewed")
            accession = incorporation.get("latest_material_accession")
            if accession and accession not in reviewed_accessions:
                reasons.append("latest_earnings_accession_not_reviewed")
        for event in material_events or []:
            if event.get("ticker") != ticker or event.get("material_event") not in {True, "yes"}:
                continue
            accession = event.get("accession_number") or event.get("accession")
            if accession in reviewed_accessions:
                continue
            accepted = context["acceptance"].get(accession, {})
            published_at = accepted.get("accepted_at")
            if published_at is None:
                reasons.append("material_event_publication_unresolved:"+str(accession))
            elif _timestamp(published_at) <= now and _timestamp(published_at) > reviewed:
                reasons.append("new_material_filing_not_reviewed:"+str(accession))
            elif _timestamp(published_at) <= reviewed and event.get("detected_at") and _timestamp(event["detected_at"]) > reviewed:
                reasons.append("late_detected_material_filing_not_reviewed:"+str(accession))
        result["reopen_reasons"] = sorted(set(reasons))
        if reasons:
            result["status"] = "reassess"
        elif result["status"] == "reviewed" and now.date() > reviewed.date():
            result["status"] = "monitor"
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result["status"] = "unresolved"
        result["validation_errors"] = [str(exc)]
        result["reopen_reasons"] = ["company_review_validation_failed"]
        result["review_record"] = None
        result["conclusion"] = ""
    return result
