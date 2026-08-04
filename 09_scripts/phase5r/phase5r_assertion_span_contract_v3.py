"""Offline assertion-to-excerpt span checks for a future Phase 5R v3 sidecar.

This is an additive prototype, not a migration or replacement for v1, v10, or
the future-v2 structural contracts.  It does not import a pilot runner,
provider, handoff, policy, credential, network, brokerage, email, scheduler,
or execution component.  Given caller-supplied packet-local excerpts, it only
proves that declared UTF-8 byte spans and literal assertion anchors are bound
to those exact excerpts.  It cannot determine semantic support, citation
accuracy, reviewer independence, factual truth, or a substantive outcome.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
import unicodedata


ASSERTION_SPAN_CONTRACT_V3_SCHEMA_VERSION = "phase5r_assertion_span_contract_v3"

_BUNDLE_FIELDS = frozenset(
    {
        "schema_version",
        "packet_id",
        "canonical_effect",
        "sources",
        "assertions",
        "anchor_reviews",
    }
)
_SOURCE_FIELDS = frozenset({"source_id", "excerpt_text", "excerpt_utf8_sha256"})
_ASSERTION_FIELDS = frozenset(
    {
        "assertion_id",
        "assertion_text",
        "assertion_utf8_sha256",
        "cited_source_ids",
    }
)
_ANCHOR_REVIEW_FIELDS = frozenset(
    {
        "assertion_id",
        "procedure_disposition",
        "anchors",
        "anchor_absence_code",
    }
)
_ANCHOR_FIELDS = frozenset(
    {
        "source_id",
        "excerpt_utf8_sha256",
        "start_utf8_byte",
        "end_utf8_byte",
        "span_utf8_sha256",
        "assertion_text_anchor",
    }
)
_ANCHOR_ABSENCE_CODES = frozenset(
    {
        "not_localizable_in_cited_excerpt",
        "excerpt_scope_insufficient",
        "citation_not_available",
    }
)
_PROCEDURE_DISPOSITIONS = frozenset(
    {"span_anchored", "anchor_not_available"}
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_NUMBER_TOKEN_PATTERN = re.compile(
    r"(?<![\w.])(?:[+-]?[$€£¥₹]?(?:\d{1,3}(?:[,٬]\d{3})+(?:[.٫]\d+)?|"
    r"\d+(?:[.٫]\d+)?|[.٫]\d+)(?:[eE][+-]?\d+)?(?:%|[A-Za-zµμ]+(?:\d+)?)?)(?!(?:\w|[,٬.٫](?=\d)))",
    flags=re.IGNORECASE,
)
_TEXTUAL_NUMBER_WORD_PATTERN = (
    r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"thousand|million|billion|trillion"
)
_TEXTUAL_NUMBER_TOKEN_PATTERN = re.compile(
    r"\b(?:"
    + _TEXTUAL_NUMBER_WORD_PATTERN
    + r")(?:[-\s]+(?:"
    + _TEXTUAL_NUMBER_WORD_PATTERN
    + r"))*\b",
    flags=re.IGNORECASE,
)
_UNIT_TOKEN_PATTERN = re.compile(
    r"\b(?:percent|percentage|million|billion|trillion|thousand|shares?|dollars?|"
    r"bps|basis\s+points|per\s+share|m|bn|mm|b|k|[kmunp]?g|[kmunp]?l|"
    r"mcg|ug|µg|μg|iu|units?)\b|%",
    flags=re.IGNORECASE,
)
_PERIOD_TOKEN_PATTERN = re.compile(
    r"(?<!\w)(?:(?:FY|CY)\d{2,4}(?:Q[1-4]|H[1-2])?E?|"
    r"(?:Q[1-4]|H[1-2])(?:FY|CY)\d{2,4}E?|"
    r"(?:19|20)\d{2}(?:Q[1-4]|H[1-2])?E?|Q[1-4]E?|H[1-2]E?|FY|CY)(?!\w)",
    flags=re.IGNORECASE,
)
_STANDALONE_ALPHA_TOKEN_PATTERN = re.compile(
    r"(?<!\w)[^\W\d_]+(?!\w)", flags=re.UNICODE
)
_SENTENCE_DELIMITERS = frozenset(".?!;\r\n。！？；…؟؛।\u2028\u2029")
_WORD_JOINERS = frozenset({"_", "+", "-", "‐", "‑", "‒", "–", "—", "−"})
_NUMERIC_PREFIX_MARKERS = frozenset(
    {"+", "-", "−", "＋", "－", "<", ">", "≤", "≥", "~", "≈"}
)
_COMPARATIVE_CUE_PATTERNS = (
    re.compile(r"\b(?:up|down)\s+from\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:up|down)\b", flags=re.IGNORECASE),
    re.compile(r"\bfrom\s+[^.?!;]{1,120}?\s+to\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:versus|vs\.?|compared\s+(?:to|with))\b", flags=re.IGNORECASE),
    re.compile(r"\b(?:year[- ]over[- ]year|yoy)\b", flags=re.IGNORECASE),
    re.compile(
        r"\b(?:increased|decreased|grew|declined|improved|worsened|higher|lower|"
        r"rose|fell|surged|jumped|plunged|doubled|halved|expanded|contracted)\b",
        flags=re.IGNORECASE,
    ),
)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "million",
        "billion",
        "thousand",
        "percent",
        "percentage",
        "share",
        "shares",
        "dollar",
        "dollars",
        "usd",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "with",
    }
)


class AssertionSpanV3Error(ValueError):
    """A future-v3 assertion/span sidecar violated its closed offline contract."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssertionSpanV3Error(f"{label}: expected object")
    return value


def _require_closed_keys(
    value: Any,
    *,
    fields: frozenset[str],
    label: str,
) -> dict[str, Any]:
    row = _require_object(value, label=label)
    if set(row) != fields:
        missing = sorted(fields - set(row))
        unexpected = sorted(set(row) - fields)
        details: list[str] = []
        if missing:
            details.append("missing " + ",".join(missing))
        if unexpected:
            details.append("unexpected " + ",".join(unexpected))
        raise AssertionSpanV3Error(
            f"{label}: field mismatch ({'; '.join(details)})"
        )
    return row


def _require_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssertionSpanV3Error(f"{label}: expected non-empty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AssertionSpanV3Error(f"{label}: expected UTF-8 Unicode scalars") from exc
    return value


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise AssertionSpanV3Error(f"{label}: invalid sha256")
    return value


def _require_identifier_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise AssertionSpanV3Error(f"{label}: expected non-empty array")
    result = [_require_text(item, label=f"{label}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise AssertionSpanV3Error(f"{label}: identifiers must be unique")
    return result


def _require_nonnegative_integer(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AssertionSpanV3Error(f"{label}: expected non-negative integer")
    return value


def _packet_source_map(packet: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    packet = _require_object(packet, label="packet")
    packet_id = _require_text(packet.get("packet_id"), label="packet.packet_id")
    catalog = packet.get("source_catalog")
    if not isinstance(catalog, list) or not catalog:
        raise AssertionSpanV3Error("packet.source_catalog: expected non-empty array")
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(catalog):
        label = f"packet.source_catalog[{index}]"
        source = _require_object(value, label=label)
        source_id = _require_text(source.get("source_id"), label=f"{label}.source_id")
        content_sha256 = _require_sha256(
            source.get("content_sha256"), label=f"{label}.content_sha256"
        )
        if source_id in result:
            raise AssertionSpanV3Error("packet.source_catalog: source_ids must be unique")
        result[source_id] = {"content_sha256": content_sha256}
    return packet_id, result


def _source_text_map(
    *,
    packet_sources: dict[str, dict[str, Any]],
    sources: Any,
) -> dict[str, dict[str, Any]]:
    if not isinstance(sources, list) or not sources:
        raise AssertionSpanV3Error("assertion_span_v3.sources: expected non-empty array")
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(sources):
        label = f"assertion_span_v3.sources[{index}]"
        source = _require_closed_keys(value, fields=_SOURCE_FIELDS, label=label)
        source_id = _require_text(source["source_id"], label=f"{label}.source_id")
        excerpt_text = _require_text(source["excerpt_text"], label=f"{label}.excerpt_text")
        excerpt_hash = _require_sha256(
            source["excerpt_utf8_sha256"], label=f"{label}.excerpt_utf8_sha256"
        )
        if source_id in result:
            raise AssertionSpanV3Error("assertion_span_v3.sources: source_ids must be unique")
        packet_source = packet_sources.get(source_id)
        if packet_source is None:
            raise AssertionSpanV3Error(f"{label}: unknown packet source")
        computed_hash = _sha256(excerpt_text.encode("utf-8"))
        if excerpt_hash != computed_hash:
            raise AssertionSpanV3Error(f"{label}: excerpt UTF-8 hash mismatch")
        if excerpt_hash != packet_source["content_sha256"]:
            raise AssertionSpanV3Error(f"{label}: packet excerpt hash mismatch")
        result[source_id] = {
            "source_id": source_id,
            "excerpt_text": excerpt_text,
            "excerpt_utf8_sha256": excerpt_hash,
        }
    if set(result) != set(packet_sources):
        raise AssertionSpanV3Error(
            "assertion_span_v3.sources: must exactly cover packet source_ids"
        )
    return result


def _assertion_map(
    assertions: Any,
    *,
    packet_sources: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    if not isinstance(assertions, list) or not assertions:
        raise AssertionSpanV3Error("assertion_span_v3.assertions: expected non-empty array")
    ordered_ids: list[str] = []
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(assertions):
        label = f"assertion_span_v3.assertions[{index}]"
        assertion = _require_closed_keys(value, fields=_ASSERTION_FIELDS, label=label)
        assertion_id = _require_text(assertion["assertion_id"], label=f"{label}.assertion_id")
        assertion_text = _require_text(
            assertion["assertion_text"], label=f"{label}.assertion_text"
        )
        assertion_hash = _require_sha256(
            assertion["assertion_utf8_sha256"],
            label=f"{label}.assertion_utf8_sha256",
        )
        if assertion_hash != _sha256(assertion_text.encode("utf-8")):
            raise AssertionSpanV3Error(f"{label}: assertion UTF-8 hash mismatch")
        cited_source_ids = _require_identifier_list(
            assertion["cited_source_ids"], label=f"{label}.cited_source_ids"
        )
        unknown_sources = sorted(set(cited_source_ids) - set(packet_sources))
        if unknown_sources:
            raise AssertionSpanV3Error(
                f"{label}: unknown cited source_ids {','.join(unknown_sources)}"
            )
        if assertion_id in result:
            raise AssertionSpanV3Error(
                "assertion_span_v3.assertions: assertion_ids must be unique"
            )
        ordered_ids.append(assertion_id)
        result[assertion_id] = {
            "assertion_id": assertion_id,
            "assertion_text": assertion_text,
            "assertion_utf8_sha256": assertion_hash,
            "cited_source_ids": tuple(cited_source_ids),
        }
    return ordered_ids, result


def _has_meaningful_token(value: str) -> bool:
    words = {
        word.casefold()
        for word in re.findall(r"[^\W\d_]{3,}", value, flags=re.UNICODE)
    }
    return bool(words - _STOP_WORDS)


def _contains_literal_anchor(
    text: str,
    anchor: str,
    *,
    preceding_text: str = "",
    following_text: str = "",
) -> bool:
    """Require a Unicode-boundary literal anchor without case-fold expansion.

    The raw span hash fixes bytes.  This additional check prevents a declared
    value from borrowing a larger number, a signed opposite, a hyphenated or
    Unicode-word fragment, or a combining-mark extension.  A language without
    separable word boundaries must provide a larger literal phrase/span rather
    than rely on a substring.  ``lower()`` permits ordinary capitalization
    changes but intentionally does not use ``casefold()``, whose expansion of
    ``ß`` to ``ss`` is not literal.
    """

    literal_text = text.lower()
    literal_anchor = anchor.lower()
    literal_preceding = preceding_text.lower()
    literal_following = following_text.lower()
    requires_lexical_boundary = any(
        _is_lexical_continuation(character) for character in literal_anchor
    )
    numeric_anchor = _NUMBER_TOKEN_PATTERN.fullmatch(literal_anchor) is not None
    offset = 0
    while True:
        start = literal_text.find(literal_anchor, offset)
        if start < 0:
            return False
        end = start + len(literal_anchor)
        before = (
            literal_text[start - 1]
            if start
            else literal_preceding[-1:]
        )
        before_previous = (
            literal_text[start - 2]
            if start > 1
            else (
                literal_preceding[-1:]
                if start == 1
                else literal_preceding[-2:-1]
            )
        )
        after = (
            literal_text[end]
            if end < len(literal_text)
            else literal_following[:1]
        )
        after_next = (
            literal_text[end + 1]
            if end + 1 < len(literal_text)
            else literal_following[1:2]
        )
        left_nonspace = (
            literal_text[:start] if start else literal_preceding
        ).rstrip()[-1:]
        numeric_continuation = (
            numeric_anchor
            and (
                (bool(after) and after in ",٬.٫" and after_next.isdigit())
                or (
                    bool(before)
                    and before in ",٬.٫"
                    and before_previous.isdigit()
                )
                or (bool(before) and before in ".٫")
                or left_nonspace == "("
                or left_nonspace in _NUMERIC_PREFIX_MARKERS
                or (bool(after) and after == "%")
            )
        )
        if not (
            requires_lexical_boundary
            and (
                _is_lexical_continuation(before)
                or _is_lexical_continuation(after)
            )
        ) and not numeric_continuation:
            return True
        offset = start + 1


def _is_lexical_continuation(character: str) -> bool:
    """Return whether a neighboring character extends a literal token."""

    return bool(character) and (
        character.isalnum()
        or character in _WORD_JOINERS
        or unicodedata.category(character).startswith("M")
    )


def _is_sentence_delimiter(text: str, position: int) -> bool:
    """Return whether a character delimits a sentence for anchor coverage."""

    character = text[position]
    if character not in _SENTENCE_DELIMITERS:
        return False
    # A decimal point belongs to the numeric token, including a leading
    # decimal such as ``.10``. Treat it as content so a relation word after
    # the number cannot escape the local anchor requirement.
    if character != "." or not text[position + 1 : position + 2].isdigit():
        return True
    before = text[position - 1 : position]
    return not (
        before.isdigit()
        or not before
        or before.isspace()
        or before in "(+-−＋－$€£¥₹"
    )


def _sentence_content_tokens_around_numeric(
    text: str,
    start: int,
) -> set[str]:
    """Return conservative literal content from a numeric assertion sentence.

    A fixed list of direction verbs cannot safely cover arbitrary modifiers:
    for example, ``accelerated approximately 10%`` would otherwise expose
    only ``approximately``. For each stated numeric value, require every
    meaningful lexical token in its sentence to appear in an anchor. This is
    deliberately stricter than semantic review: a paraphrased source can be
    marked incomplete, but an unanchored direction, qualifier, negation, or
    trailing comparison cannot receive a completed structural result.
    """

    sentence_start = 0
    for position in range(start - 1, -1, -1):
        if _is_sentence_delimiter(text, position):
            sentence_start = position + 1
            break
    sentence_end = len(text)
    for position in range(start, len(text)):
        if _is_sentence_delimiter(text, position):
            sentence_end = position
            break
    sentence = text[sentence_start:sentence_end]
    tokens = {
        match.group(0)
        for match in _STANDALONE_ALPHA_TOKEN_PATTERN.finditer(sentence)
        if match.group(0).casefold() not in _STOP_WORDS
        and (len(match.group(0)) >= 2 or match.group(0).casefold() in {"q", "y"})
    }
    return tokens


def _sentence_ranges(text: str) -> list[tuple[int, int]]:
    """Return character ranges for local excerpt sentences."""

    ranges: list[tuple[int, int]] = []
    start = 0
    for position in range(len(text)):
        if _is_sentence_delimiter(text, position):
            if start < position:
                ranges.append((start, position + 1))
            start = position + 1
    if start < len(text):
        ranges.append((start, len(text)))
    return ranges


def _has_atomic_deterministic_anchor(
    *,
    required_tokens: set[str],
    anchor_texts: list[str],
) -> bool:
    """Require one literal anchor phrase to bind all deterministic tokens.

    A same-sentence union of tiny anchors can still pair a subject from one
    clause with a direction and quantity from another. Requiring one declared
    anchor phrase containing every deterministic token is deliberately more
    conservative: it preserves an exact local textual binding without making
    a semantic-entailment judgment.
    """

    return any(
        all(_contains_literal_anchor(anchor_text, token) for token in required_tokens)
        for anchor_text in anchor_texts
    )


def _deterministic_anchor_tokens(assertion_text: str) -> set[str]:
    """Return conservative literal tokens that must appear in an anchor.

    This is intentionally a textual guard, not a semantic parser.  It catches
    unanchored stated numbers, units, years, and common comparative wording;
    an assertion that cannot localize one of these cues stays incomplete.
    """

    tokens: set[str] = set()
    for match in _NUMBER_TOKEN_PATTERN.finditer(assertion_text):
        token = match.group(0)
        sentence_tokens = _sentence_content_tokens_around_numeric(
            assertion_text, match.start()
        )
        unadorned = token.replace(",", "").lstrip("+-€£$").rstrip("%xX")
        if (
            token == unadorned
            and unadorned.isascii()
            and len(unadorned) == 4
            and unadorned.isdigit()
        ):
            year = int(unadorned)
            if 1900 <= year <= 2100:
                # The calendar token is bound by the period grammar below,
                # but its assertion sentence still needs content coverage.
                tokens.update(sentence_tokens)
                continue
        tokens.add(token)
        tokens.update(sentence_tokens)
    for match in _TEXTUAL_NUMBER_TOKEN_PATTERN.finditer(assertion_text):
        tokens.update(
            _sentence_content_tokens_around_numeric(assertion_text, match.start())
        )
    tokens.update(
        match.group(0) for match in _TEXTUAL_NUMBER_TOKEN_PATTERN.finditer(assertion_text)
    )
    tokens.update(match.group(0) for match in _UNIT_TOKEN_PATTERN.finditer(assertion_text))
    for match in _PERIOD_TOKEN_PATTERN.finditer(assertion_text):
        tokens.add(match.group(0))
        tokens.update(
            _sentence_content_tokens_around_numeric(assertion_text, match.start())
        )
    tokens.update(
        match.group(0)
        for pattern in _COMPARATIVE_CUE_PATTERNS
        for match in pattern.finditer(assertion_text)
    )
    return tokens


def _validate_anchor(
    anchor: Any,
    *,
    label: str,
    assertion_text: str,
    cited_source_ids: set[str],
    source_map: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    row = dict(_require_closed_keys(anchor, fields=_ANCHOR_FIELDS, label=label))
    source_id = _require_text(row["source_id"], label=f"{label}.source_id")
    if source_id not in cited_source_ids:
        raise AssertionSpanV3Error(f"{label}: source_id is not cited by assertion")
    source = source_map[source_id]
    excerpt_hash = _require_sha256(
        row["excerpt_utf8_sha256"], label=f"{label}.excerpt_utf8_sha256"
    )
    if excerpt_hash != source["excerpt_utf8_sha256"]:
        raise AssertionSpanV3Error(f"{label}: stale excerpt UTF-8 hash")
    start = _require_nonnegative_integer(
        row["start_utf8_byte"], label=f"{label}.start_utf8_byte"
    )
    end = _require_nonnegative_integer(
        row["end_utf8_byte"], label=f"{label}.end_utf8_byte"
    )
    source_raw = source["excerpt_text"].encode("utf-8")
    if start >= end or end > len(source_raw):
        raise AssertionSpanV3Error(f"{label}: invalid UTF-8 byte range")
    try:
        prefix_text = source_raw[:start].decode("utf-8")
        span_text = source_raw[start:end].decode("utf-8")
        suffix_text = source_raw[end:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AssertionSpanV3Error(f"{label}: offsets must be UTF-8 boundaries") from exc
    span_hash = _require_sha256(row["span_utf8_sha256"], label=f"{label}.span_utf8_sha256")
    if span_hash != _sha256(source_raw[start:end]):
        raise AssertionSpanV3Error(f"{label}: span UTF-8 hash mismatch")
    assertion_text_anchor = _require_text(
        row["assertion_text_anchor"], label=f"{label}.assertion_text_anchor"
    )
    if not _contains_literal_anchor(assertion_text, assertion_text_anchor):
        raise AssertionSpanV3Error(f"{label}: assertion_text_anchor is absent from assertion")
    if not _contains_literal_anchor(
        span_text,
        assertion_text_anchor,
        preceding_text=prefix_text,
        following_text=suffix_text,
    ):
        raise AssertionSpanV3Error(
            f"{label}: assertion_text_anchor is absent from excerpt span"
        )
    span_start = len(prefix_text)
    span_end = span_start + len(span_text)
    if not any(
        sentence_start <= span_start and span_end <= sentence_end
        for sentence_start, sentence_end in _sentence_ranges(source["excerpt_text"])
    ):
        raise AssertionSpanV3Error(
            f"{label}: anchor span must remain within one source sentence"
        )
    return source_id, assertion_text_anchor


def _validate_anchor_reviews(
    anchor_reviews: Any,
    *,
    assertion_ids: list[str],
    assertions: dict[str, dict[str, Any]],
    source_map: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    if not isinstance(anchor_reviews, list) or not anchor_reviews:
        raise AssertionSpanV3Error("assertion_span_v3.anchor_reviews: expected non-empty array")
    reviews = list(anchor_reviews)
    reviewed_ids: list[str] = []
    anchored_count = 0
    unavailable_count = 0
    for index, value in enumerate(reviews):
        label = f"assertion_span_v3.anchor_reviews[{index}]"
        review = dict(
            _require_closed_keys(value, fields=_ANCHOR_REVIEW_FIELDS, label=label)
        )
        assertion_id = _require_text(review["assertion_id"], label=f"{label}.assertion_id")
        if assertion_id not in assertions:
            raise AssertionSpanV3Error(f"{label}: unknown assertion_id")
        reviewed_ids.append(assertion_id)
        disposition = _require_text(
            review["procedure_disposition"], label=f"{label}.procedure_disposition"
        )
        if disposition not in _PROCEDURE_DISPOSITIONS:
            raise AssertionSpanV3Error(f"{label}: unsupported procedure_disposition")
        anchors = review["anchors"]
        if not isinstance(anchors, list):
            raise AssertionSpanV3Error(f"{label}.anchors: expected array")
        anchors = list(anchors)
        absence_code = review["anchor_absence_code"]
        if disposition == "anchor_not_available":
            if anchors:
                raise AssertionSpanV3Error(
                    f"{label}: anchor_not_available requires empty anchors"
                )
            absence_code = _require_text(absence_code, label=f"{label}.anchor_absence_code")
            if absence_code not in _ANCHOR_ABSENCE_CODES:
                raise AssertionSpanV3Error(f"{label}: unsupported anchor_absence_code")
            unavailable_count += 1
            continue
        if absence_code is not None:
            raise AssertionSpanV3Error(f"{label}: span_anchored requires null anchor_absence_code")
        if not anchors:
            raise AssertionSpanV3Error(f"{label}: span_anchored requires anchors")
        assertion = assertions[assertion_id]
        cited_source_ids = set(assertion["cited_source_ids"])
        anchored_source_ids: set[str] = set()
        anchor_texts: list[str] = []
        seen_anchor_locations: set[tuple[str, int, int, str]] = set()
        for anchor_index, anchor in enumerate(anchors):
            anchor_label = f"{label}.anchors[{anchor_index}]"
            source_id, anchor_text = _validate_anchor(
                anchor,
                label=anchor_label,
                assertion_text=assertion["assertion_text"],
                cited_source_ids=cited_source_ids,
                source_map=source_map,
            )
            start = anchor["start_utf8_byte"]
            end = anchor["end_utf8_byte"]
            location = (source_id, start, end, anchor_text)
            if location in seen_anchor_locations:
                raise AssertionSpanV3Error(f"{label}: anchors must be unique")
            seen_anchor_locations.add(location)
            anchored_source_ids.add(source_id)
            anchor_texts.append(anchor_text)
        if anchored_source_ids != cited_source_ids:
            raise AssertionSpanV3Error(
                f"{label}: anchors must cover exactly the cited source_ids"
            )
        if not any(_has_meaningful_token(anchor_text) for anchor_text in anchor_texts):
            raise AssertionSpanV3Error(
                f"{label}: anchors require a meaningful literal assertion overlap"
            )
        required_tokens = _deterministic_anchor_tokens(assertion["assertion_text"])
        missing_tokens = sorted(
            token
            for token in required_tokens
            if not any(
                _contains_literal_anchor(anchor_text, token)
                for anchor_text in anchor_texts
            )
        )
        if missing_tokens:
            raise AssertionSpanV3Error(
                f"{label}: required deterministic text anchors are missing"
            )
        if required_tokens and not _has_atomic_deterministic_anchor(
            required_tokens=required_tokens,
            anchor_texts=anchor_texts,
        ):
            raise AssertionSpanV3Error(
                f"{label}: required deterministic tokens need one atomic literal anchor"
            )
        anchored_count += 1
    if reviewed_ids != assertion_ids:
        raise AssertionSpanV3Error(
            "assertion_span_v3.anchor_reviews: must exactly cover assertion_ids in order"
        )
    return anchored_count, unavailable_count


def evaluate_assertion_span_procedure_v3(
    *,
    packet: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    """Validate structural assertion spans without issuing a semantic judgment.

    ``packet`` must already be retained by a separately authorized future
    workflow.  This function only binds the bundle's local excerpt text to the
    packet source hashes; it does not establish that the upstream packet is
    otherwise valid or that an excerpt entails an assertion.
    """

    packet_id, packet_sources = _packet_source_map(packet)
    bundle = _require_closed_keys(bundle, fields=_BUNDLE_FIELDS, label="assertion_span_v3")
    if bundle["schema_version"] != ASSERTION_SPAN_CONTRACT_V3_SCHEMA_VERSION:
        raise AssertionSpanV3Error("assertion_span_v3: schema version mismatch")
    if bundle["packet_id"] != packet_id:
        raise AssertionSpanV3Error("assertion_span_v3: packet_id mismatch")
    if bundle["canonical_effect"] is not False:
        raise AssertionSpanV3Error("assertion_span_v3: canonical_effect must remain false")
    source_map = _source_text_map(packet_sources=packet_sources, sources=bundle["sources"])
    assertion_ids, assertions = _assertion_map(
        bundle["assertions"], packet_sources=packet_sources
    )
    anchored_count, unavailable_count = _validate_anchor_reviews(
        bundle["anchor_reviews"],
        assertion_ids=assertion_ids,
        assertions=assertions,
        source_map=source_map,
    )
    return {
        "schema_version": ASSERTION_SPAN_CONTRACT_V3_SCHEMA_VERSION,
        "procedure_status": (
            "completed" if unavailable_count == 0 else "incomplete"
        ),
        "assertion_count": len(assertion_ids),
        "span_anchored_count": anchored_count,
        "anchor_not_available_count": unavailable_count,
        "packet_source_hash_binding_status": "validated_but_not_upstream_verified",
        "assertion_origin_status": "caller_supplied_unverified",
        "semantic_status": "not_assessed",
        "citation_accuracy_status": "not_assessed",
        "substantive_recommendation": "not_established",
        "canonical_effect": False,
        "execution_authority": False,
        "provider_or_network_used_by_verifier": False,
    }
