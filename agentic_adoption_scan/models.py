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


@dataclass
class ActivityResult:
    scan_timestamp: str
    org: str
    repo: str
    repo_visibility: str
    week_start: str
    tool: str
    signal: str
    count: int
    total_commits: int


@dataclass
class CommitInfo:
    committed_date: str
    message: str


@dataclass
class PullInfo:
    created_at: str
    author_login: str


@dataclass
class ReviewInfo:
    submitted_at: str
    author_login: str
