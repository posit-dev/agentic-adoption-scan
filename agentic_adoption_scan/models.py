from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScanResult:
    scan_timestamp: str
    org: str
    repo: str
    repo_visibility: str
    repo_language: str
    repo_pushed_at: str
    category: str
    indicator: str
    found: bool
    file_path: str
    details: str


@dataclass
class InspectResult:
    scan_timestamp: str
    org: str
    repo: str
    category: str
    indicator: str
    file_path: str
    content_size: int
    content_summary: str
    raw_content: str
