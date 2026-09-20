"""Extract a narrowly approved issuer cash-flow fact from official inline XBRL.

SEC companyfacts excludes custom taxonomy facts. NVIDIA's financed-asset
principal is necessary for its disclosed FCF definition, so retain the exact
consolidated duration, USD unit, accession, acceptance time and raw hash.
No free-text inference and no missing-as-zero substitution are permitted.
"""
from __future__ import annotations

import copy
import hashlib
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from phase5r_daily_common import ROOT, atomic_write_json, read_json
from refresh_phase5r_sec_filing_artifacts import atomic_write_bytes, fetch_sec_document

NVDA_PRINCIPAL_TAG = "PaymentsForFinancedPropertyPlantAndEquipmentAndIntangibleAssetsFinancingActivities"
CACHE_ROOT = ROOT / "02_filings" / "phase5r_daily" / "financial_supplements.local"
MAX_RAW_BYTES = 15 * 1024 * 1024


class SupplementalFactError(ValueError):
    pass


class InlineFacts(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.contexts: dict[str, dict[str, Any]] = {}
        self.units: dict[str, list[str]] = {}
        self.facts: list[dict[str, Any]] = []
        self.context: dict[str, Any] | None = None
        self.unit: tuple[str, list[str]] | None = None
        self.fact: dict[str, Any] | None = None
        self.capture: str | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs)
        local = tag.split(":")[-1].lower()
        if tag == "xbrli:context":
            self.context = {"id": attrs.get("id"), "dimensional": False}
        elif self.context is not None and local in {"explicitmember", "typedmember", "segment", "scenario"}:
            self.context["dimensional"] = True
        elif self.context is not None and local in {"identifier", "startdate", "enddate", "instant"}:
            self.capture, self.text = local, []
        elif tag == "xbrli:unit":
            self.unit = (attrs.get("id", ""), [])
        elif self.unit is not None and local == "measure":
            self.capture, self.text = "measure", []
        elif tag == "ix:nonfraction" and attrs.get("name") == "nvda:" + NVDA_PRINCIPAL_TAG:
            self.fact = {**attrs, "text": ""}

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.text.append(data)
        if self.fact is not None:
            self.fact["text"] += data

    def handle_endtag(self, tag: str) -> None:
        local = tag.split(":")[-1].lower()
        if self.capture == local:
            text = "".join(self.text).strip()
            if local == "measure" and self.unit is not None:
                self.unit[1].append(text)
            elif self.context is not None:
                self.context[local] = text
            self.capture, self.text = None, []
        if tag == "xbrli:context" and self.context is not None:
            self.contexts[self.context["id"]] = self.context
            self.context = None
        elif tag == "xbrli:unit" and self.unit is not None:
            self.units[self.unit[0]] = self.unit[1]
            self.unit = None
        elif tag == "ix:nonfraction" and self.fact is not None:
            self.facts.append(self.fact)
            self.fact = None


def parse_principal_facts(raw: bytes, *, filing: dict[str, str], cik: int,
                          source_url: str, raw_path: str) -> list[dict[str, Any]]:
    if len(raw) > MAX_RAW_BYTES:
        raise SupplementalFactError("supplemental_document_too_large")
    parser = InlineFacts()
    parser.feed(raw.decode("utf-8"))
    result: dict[tuple[str, str], dict[str, Any]] = {}
    digest = hashlib.sha256(raw).hexdigest()
    for fact in parser.facts:
        context = parser.contexts.get(fact.get("contextref", ""), {})
        if context.get("dimensional"):
            continue
        if not context.get("identifier", "").isdigit() or int(context["identifier"]) != cik:
            raise SupplementalFactError("supplemental_cik_conflict")
        if parser.units.get(fact.get("unitref", "")) != ["iso4217:USD"]:
            raise SupplementalFactError("supplemental_unit_conflict")
        start, end = context.get("startdate", ""), context.get("enddate", "")
        try:
            start_day, end_day = datetime.fromisoformat(start), datetime.fromisoformat(end)
            filed = datetime.fromisoformat(filing["filing_date"])
            if start_day >= end_day or end_day > filed:
                raise ValueError()
            scale = int(fact.get("scale", "0"))
            if abs(scale) > 12 or fact.get("sign", "") not in {"", "-"}:
                raise ValueError()
            text = fact["text"].strip().replace(",", "")
            if fact.get("format") in {"ixt:fixed-zero", "ixt:zerodash"} and text in {"—", "-", "–", "0"}:
                number = Decimal(0)
            elif fact.get("format", "") in {"ixt:num-dot-decimal", "ixt:numdotdecimal", ""} and re.fullmatch(r"\d+(?:\.\d+)?", text):
                number = Decimal(text) * (Decimal(10) ** scale)
            else:
                raise ValueError()
            if fact.get("sign") == "-" or number < 0 or not number.is_finite():
                raise ValueError()
        except (ValueError, InvalidOperation, KeyError):
            raise SupplementalFactError("invalid_supplemental_numeric_fact") from None
        row = {"start": start, "end": end, "val": float(number),
            "filed": filing["filing_date"], "accn": filing["accession_number"],
            "form": filing["form"], "_source_url": source_url,
            "_raw_sha256": digest, "_raw_path": raw_path, "_context_id": context["id"],
            "_fact_id": fact.get("id", "")}
        key = (start, end)
        if key in result and result[key]["val"] != row["val"]:
            raise SupplementalFactError("conflicting_supplemental_facts")
        result[key] = row
    if not result:
        raise SupplementalFactError("supplemental_principal_fact_not_reported")
    return list(result.values())


def supplement_companyfacts(ticker: str, cik: int, payload: dict[str, Any],
        filings: list[dict[str, str]], user_agent: str, *, as_of: datetime,
        cache_root: Path = CACHE_ROOT, fetcher: Any = fetch_sec_document) -> dict[str, Any]:
    if ticker != "NVDA" or cik != 1045810:
        return payload
    selected = []
    for form in ("10-K", "10-Q"):
        candidates = [row for row in filings if row["form"] == form
                      and datetime.fromisoformat(row["accepted_at"].replace("Z", "+00:00")) <= as_of]
        if candidates:
            selected.append(max(candidates, key=lambda row: (row["filing_date"], row["accepted_at"])))
    values = []
    for filing in selected:
        accession, document = filing["accession_number"], filing["primary_document"]
        if (not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", document)):
            raise SupplementalFactError("invalid_supplemental_filing_identity")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{document}"
        directory = cache_root / ticker / accession
        raw_path, receipt_path = directory / "primary_document.raw", directory / "receipt.json"
        receipt = read_json(receipt_path, {})
        raw = raw_path.read_bytes() if raw_path.is_file() and raw_path.stat().st_size <= MAX_RAW_BYTES else b""
        cache_valid = (bool(raw) and receipt.get("source_url") == url
                       and receipt.get("accepted_at") == filing["accepted_at"]
                       and receipt.get("raw_sha256") == hashlib.sha256(raw).hexdigest())
        if not cache_valid:
            result = fetcher(url, user_agent, max_bytes=MAX_RAW_BYTES)
            raw = result.raw_bytes
        parsed = parse_principal_facts(raw, filing=filing, cik=cik, source_url=url, raw_path=str(raw_path))
        if not cache_valid:
            atomic_write_bytes(raw_path, raw)
            atomic_write_json(receipt_path, {"schema_version": "phase5r_sec_supplemental_fact_v1",
                "ticker": ticker, "cik": cik, "source_url": url,
                "accession": accession, "accepted_at": filing["accepted_at"],
                "raw_sha256": hashlib.sha256(raw).hexdigest(), "fetched_at": as_of.isoformat()})
        values.extend(parsed)
    enriched = copy.deepcopy(payload)
    enriched.setdefault("facts", {}).setdefault("nvda", {})[NVDA_PRINCIPAL_TAG] = {"units": {"USD": values}}
    return enriched
