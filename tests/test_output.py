from __future__ import annotations

import csv
import io

from agentic_adoption_scan.models import InspectResult, ScanResult
from agentic_adoption_scan.output import write_inspect_csv, write_scan_csv


def test_write_scan_csv_header_and_data():
    results = [
        ScanResult(
            scan_timestamp="2026-03-23T00:00:00Z",
            org="test-org",
            repo="test-repo",
            repo_visibility="public",
            repo_language="Go",
            repo_pushed_at="2026-03-22T00:00:00Z",
            category="claude-code",
            indicator="CLAUDE.md",
            found=True,
            file_path="CLAUDE.md",
            details="",
        )
    ]

    buf = io.StringIO()
    write_scan_csv(buf, results)
    output = buf.getvalue()

    assert "scan_timestamp" in output
    assert "test-repo" in output
    assert "true" in output


def test_write_scan_csv_columns():
    results = [
        ScanResult(
            scan_timestamp="2026-03-23T00:00:00Z",
            org="my-org",
            repo="my-repo",
            repo_visibility="private",
            repo_language="Python",
            repo_pushed_at="2026-03-21T00:00:00Z",
            category="cursor",
            indicator=".cursorrules",
            found=False,
            file_path="",
            details="",
        )
    ]

    buf = io.StringIO()
    write_scan_csv(buf, results)
    buf.seek(0)

    reader = csv.DictReader(buf)
    rows = list(reader)
    assert len(rows) == 1
    row = rows[0]

    expected_columns = [
        "scan_timestamp", "org", "repo", "repo_visibility", "repo_language",
        "repo_pushed_at", "category", "indicator", "found", "file_path", "details",
    ]
    for col in expected_columns:
        assert col in row, f"missing column: {col}"

    assert row["found"] == "false"
    assert row["repo"] == "my-repo"


def test_write_scan_csv_empty():
    buf = io.StringIO()
    write_scan_csv(buf, [])
    output = buf.getvalue()
    # Header should still be written
    assert "scan_timestamp" in output


def test_write_inspect_csv_header_and_data():
    results = [
        InspectResult(
            scan_timestamp="2026-03-23T00:00:00Z",
            org="test-org",
            repo="test-repo",
            category="claude-code",
            indicator="CLAUDE.md",
            file_path="CLAUDE.md",
            content_size=42,
            content_summary="headings: # Overview",
            raw_content="# Overview\nSome content",
        )
    ]

    buf = io.StringIO()
    write_inspect_csv(buf, results)
    output = buf.getvalue()

    assert "scan_timestamp" in output
    assert "test-repo" in output
    assert "42" in output


def test_write_inspect_csv_columns():
    results = [
        InspectResult(
            scan_timestamp="2026-03-23T00:00:00Z",
            org="org",
            repo="repo",
            category="mcp",
            indicator="mcp.json",
            file_path="mcp.json",
            content_size=100,
            content_summary="servers: my-server",
            raw_content='{"mcpServers": {}}',
        )
    ]

    buf = io.StringIO()
    write_inspect_csv(buf, results)
    buf.seek(0)

    reader = csv.DictReader(buf)
    rows = list(reader)
    assert len(rows) == 1
    row = rows[0]

    expected_columns = [
        "scan_timestamp", "org", "repo", "category", "indicator",
        "file_path", "content_size", "content_summary", "raw_content",
    ]
    for col in expected_columns:
        assert col in row, f"missing column: {col}"

    assert row["content_size"] == "100"


def test_csv_round_trip_scan():
    """Write then re-read scan results and verify all fields survive."""
    original = ScanResult(
        scan_timestamp="2026-03-23T12:00:00Z",
        org="posit-dev",
        repo="rstudio",
        repo_visibility="public",
        repo_language="C++",
        repo_pushed_at="2026-03-20T00:00:00Z",
        category="github-copilot",
        indicator="copilot instructions",
        found=True,
        file_path=".github/copilot-instructions.md",
        details="1 matches",
    )

    buf = io.StringIO()
    write_scan_csv(buf, [original])
    buf.seek(0)

    reader = csv.DictReader(buf)
    rows = list(reader)
    assert len(rows) == 1
    row = rows[0]

    assert row["scan_timestamp"] == original.scan_timestamp
    assert row["org"] == original.org
    assert row["repo"] == original.repo
    assert row["repo_visibility"] == original.repo_visibility
    assert row["repo_language"] == original.repo_language
    assert row["repo_pushed_at"] == original.repo_pushed_at
    assert row["category"] == original.category
    assert row["indicator"] == original.indicator
    assert row["found"] == "true"
    assert row["file_path"] == original.file_path
    assert row["details"] == original.details
