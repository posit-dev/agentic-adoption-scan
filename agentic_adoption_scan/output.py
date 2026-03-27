from __future__ import annotations

import csv
from typing import IO

from .models import InspectResult, ScanResult


def write_scan_csv(writer: IO[str], results: list[ScanResult]) -> None:
    """Write scan results in tidy data format (11-column CSV)."""
    w = csv.writer(writer)

    header = [
        "scan_timestamp",
        "org",
        "repo",
        "repo_visibility",
        "repo_language",
        "repo_pushed_at",
        "category",
        "indicator",
        "found",
        "file_path",
        "details",
    ]
    w.writerow(header)

    for r in results:
        w.writerow([
            r.scan_timestamp,
            r.org,
            r.repo,
            r.repo_visibility,
            r.repo_language,
            r.repo_pushed_at,
            r.category,
            r.indicator,
            "true" if r.found else "false",
            r.file_path,
            r.details,
        ])


def write_inspect_csv(writer: IO[str], results: list[InspectResult]) -> None:
    """Write inspection results as CSV (9-column CSV)."""
    w = csv.writer(writer)

    header = [
        "scan_timestamp",
        "org",
        "repo",
        "category",
        "indicator",
        "file_path",
        "content_size",
        "content_summary",
        "raw_content",
    ]
    w.writerow(header)

    for r in results:
        w.writerow([
            r.scan_timestamp,
            r.org,
            r.repo,
            r.category,
            r.indicator,
            r.file_path,
            str(r.content_size),
            r.content_summary,
            r.raw_content,
        ])
