"""Compact (deduplicate) scan rows to the latest scan per org/repo."""
from __future__ import annotations

from agentic_adoption_scan.parquet_io import ScanRow


def deduplicate_scan_rows(rows: list[ScanRow]) -> list[ScanRow]:
    """Keep only the rows from the most recent scan_timestamp for each (org, repo) pair."""
    latest: dict[str, str] = {}
    for r in rows:
        key = f"{r.org}/{r.repo}"
        if r.scan_timestamp > latest.get(key, ""):
            latest[key] = r.scan_timestamp

    return [r for r in rows if r.scan_timestamp == latest.get(f"{r.org}/{r.repo}")]
