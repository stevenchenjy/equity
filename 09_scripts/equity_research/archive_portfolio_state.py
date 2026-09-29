#!/usr/bin/env python3
"""Snapshot active portfolio files without changing any decision input."""

from __future__ import annotations

from portfolio_archive import snapshot_active_portfolio
from daily_common import DAILY_PIPELINE_LOCK_PATH, ROOT, ExclusiveFileLock


if __name__ == "__main__":
    with ExclusiveFileLock(DAILY_PIPELINE_LOCK_PATH):
        archives = snapshot_active_portfolio(ROOT)
    print(f"portfolio_versions_verified={len(archives)} active_files_changed=false")
