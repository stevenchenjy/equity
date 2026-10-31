"""Public instrument identity, separate from candidate and capital authority."""
from __future__ import annotations

import csv
from datetime import date
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from daily_common import ROOT

RELATIVE = "01_policies/supplemental_instrument_metadata.json"
UNIVERSE = "03_source_data/equity_research/universe_seed.csv"


def supplemental(root: Path) -> dict[str, str]:
    path = root / RELATIVE
    if not path.exists():
        return {}  # Existing installations and isolated fixtures need no overrides.
    if (path.is_symlink() or path.parent.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 100_000):
        raise ValueError("instrument_metadata_invalid")
    value = json.loads(path.read_text())
    if (not isinstance(value, dict)
            or value.get("schema_version") != "equity_supplemental_instrument_metadata_v1"
            or not isinstance(value.get("instruments"), list)):
        raise ValueError("instrument_metadata_invalid")
    result = {}
    for row in value["instruments"]:
        if not isinstance(row, dict):
            raise ValueError("instrument_metadata_invalid")
        ticker = row.get("ticker")
        source = urlsplit(str(row.get("source_url", "")))
        if (not isinstance(ticker, str) or re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", ticker) is None
                or ticker in result or row.get("asset_class") not in {"stocks", "etf"}
                or not isinstance(row.get("name"), str) or not row["name"].strip()
                or source.scheme != "https" or not source.netloc or source.username or source.password):
            raise ValueError("instrument_metadata_invalid")
        try:
            date.fromisoformat(row["reviewed_on"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("instrument_metadata_invalid") from None
        result[ticker] = row["asset_class"]
    return result


def asset_class(ticker: str, *, root: Path = ROOT, universe=None) -> str | None:
    """Classify an identified public instrument; unknown symbols stay unknown."""
    if universe is None:
        path = root / UNIVERSE
        if path.exists():
            with path.open(newline="") as handle:
                universe = list(csv.DictReader(handle))
        else:
            universe = []
    rows = list(universe.values()) if isinstance(universe, dict) else list(universe)
    matches = [row for row in rows if str(row.get("ticker", "")).strip().upper() == ticker]
    if len(matches) > 1:
        raise ValueError("instrument_metadata_duplicate_universe_symbol")
    existing = ("etf" if str(matches[0].get("sector", "")).upper() == "ETF" else "stocks") if matches else None
    extra = supplemental(root).get(ticker)
    if existing is not None and extra is not None and existing != extra:
        raise ValueError("instrument_metadata_classification_conflict")
    return existing or extra


def is_fund(ticker: str, *, root: Path = ROOT, universe=None) -> bool:
    return asset_class(ticker, root=root, universe=universe) == "etf"
