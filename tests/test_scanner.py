"""Scanner tests with a mocked GitHubClient.

Covers:
- scan() with a cache hit (repo fresh → reuses cached results)
- scan() with a cache miss (repo stale → calls GitHub API)
- _filter_repos() excludes archived and old repos
- _scan_repo() dispatches correctly for each SearchType
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from agentic_adoption_scan.cache import Cache, CachedIndicator
from agentic_adoption_scan.github import Repo, SearchResult
from agentic_adoption_scan.indicators import Indicator, SearchType
from agentic_adoption_scan.models import ScanResult
from agentic_adoption_scan.scanner import Scanner
from agentic_adoption_scan.storage import LocalStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
_ACTIVE_SINCE = _NOW - timedelta(days=90)


def _make_repo(
    name: str,
    pushed_at: str = "2024-05-01T00:00:00Z",
    archived: bool = False,
    visibility: str = "public",
    language: str = "Python",
) -> Repo:
    return Repo(
        name=name,
        full_name=f"testorg/{name}",
        archived=archived,
        visibility=visibility,
        language=language,
        pushed_at=pushed_at,
    )


def _make_cache(tmp_dir: str, data: dict | None = None) -> Cache:
    store = LocalStore()
    base_path = tmp_dir
    return Cache(tmp_dir, store, base_path, data or {})


def _make_scanner(
    client: MagicMock,
    cache: Cache,
    indicators: list[Indicator] | None = None,
    active_since: datetime | None = None,
    include_archived: bool = False,
    force: bool = False,
) -> Scanner:
    return Scanner(
        client=client,
        cache=cache,
        org="testorg",
        indicators=indicators or [],
        active_since=active_since or _ACTIVE_SINCE,
        include_archived=include_archived,
        force=force,
    )


# ---------------------------------------------------------------------------
# scan() — cache hit
# ---------------------------------------------------------------------------


def test_scan_cache_hit():
    """When the cache is fresh (pushed_at unchanged), scan uses cached results."""
    from agentic_adoption_scan.cache import CachedRepo

    pushed_at = "2024-05-01T00:00:00Z"
    repo = _make_repo("myrepo", pushed_at=pushed_at)

    client = MagicMock()
    client.list_org_repos.return_value = [repo]

    with tempfile.TemporaryDirectory() as tmp_dir:
        cached_indicator = CachedIndicator(
            category="claude-code",
            indicator="CLAUDE.md",
            found=True,
            file_path="CLAUDE.md",
            details="",
            scanned_at="2024-04-30T10:00:00Z",
        )
        cache_data = {
            "testorg/myrepo": CachedRepo(
                pushed_at=pushed_at,
                scanned_at="2024-04-30T10:00:00Z",
                indicators=[cached_indicator],
            )
        }
        cache = _make_cache(tmp_dir, cache_data)
        scanner = _make_scanner(client, cache)
        results = scanner.scan()

    # GitHub API should NOT have been called for repo contents
    client.check_path_exists.assert_not_called()
    client.search_code.assert_not_called()

    assert len(results) == 1
    r = results[0]
    assert r.repo == "myrepo"
    assert r.found is True
    assert r.indicator == "CLAUDE.md"
    assert r.scan_timestamp == "2024-04-30T10:00:00Z"


# ---------------------------------------------------------------------------
# scan() — cache miss
# ---------------------------------------------------------------------------


def test_scan_cache_miss_calls_api():
    """When the cache is stale, scan calls the GitHub API and updates the cache."""
    pushed_at = "2024-05-20T00:00:00Z"   # newer than what's cached
    repo = _make_repo("myrepo", pushed_at=pushed_at)

    indicator = Indicator(
        category="claude-code",
        name="CLAUDE.md",
        search_type=SearchType.FILE_EXISTS,
        target="CLAUDE.md",
        description="test",
    )

    client = MagicMock()
    client.list_org_repos.return_value = [repo]
    client.check_path_exists.return_value = (True, False)

    with tempfile.TemporaryDirectory() as tmp_dir:
        from agentic_adoption_scan.cache import CachedRepo

        # Cache has old pushed_at → stale
        stale_data = {
            "testorg/myrepo": CachedRepo(
                pushed_at="2024-04-01T00:00:00Z",
                scanned_at="2024-04-01T10:00:00Z",
                indicators=[],
            )
        }
        cache = _make_cache(tmp_dir, stale_data)
        scanner = _make_scanner(client, cache, indicators=[indicator])
        results = scanner.scan()

    client.check_path_exists.assert_called_once_with("testorg", "myrepo", "CLAUDE.md")
    assert len(results) == 1
    assert results[0].found is True
    assert results[0].file_path == "CLAUDE.md"


def test_scan_force_bypasses_cache():
    """force=True always re-scans even when the cache appears fresh."""
    pushed_at = "2024-05-01T00:00:00Z"
    repo = _make_repo("myrepo", pushed_at=pushed_at)

    indicator = Indicator(
        category="claude-code",
        name="CLAUDE.md",
        search_type=SearchType.FILE_EXISTS,
        target="CLAUDE.md",
        description="test",
    )

    client = MagicMock()
    client.list_org_repos.return_value = [repo]
    client.check_path_exists.return_value = (False, False)

    with tempfile.TemporaryDirectory() as tmp_dir:
        from agentic_adoption_scan.cache import CachedRepo
        from agentic_adoption_scan.cache import CachedIndicator as CI

        # Cache has matching pushed_at → would be fresh without force
        fresh_data = {
            "testorg/myrepo": CachedRepo(
                pushed_at=pushed_at,
                scanned_at="2024-04-30T10:00:00Z",
                indicators=[CI("claude-code", "CLAUDE.md", True, "CLAUDE.md", "", "2024-04-30T10:00:00Z")],
            )
        }
        cache = _make_cache(tmp_dir, fresh_data)
        scanner = _make_scanner(client, cache, indicators=[indicator], force=True)
        results = scanner.scan()

    # force=True → API must have been called
    client.check_path_exists.assert_called_once()
    assert results[0].found is False


# ---------------------------------------------------------------------------
# _filter_repos()
# ---------------------------------------------------------------------------


def test_filter_repos_excludes_archived():
    active = _make_repo("active")
    archived = _make_repo("archived", archived=True)

    client = MagicMock()
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = _make_cache(tmp_dir)
        scanner = _make_scanner(client, cache, include_archived=False)
        result = scanner._filter_repos([active, archived])

    assert [r.name for r in result] == ["active"]


def test_filter_repos_includes_archived_when_flag_set():
    active = _make_repo("active")
    archived = _make_repo("archived", archived=True)

    client = MagicMock()
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = _make_cache(tmp_dir)
        scanner = _make_scanner(client, cache, include_archived=True)
        result = scanner._filter_repos([active, archived])

    assert len(result) == 2


def test_filter_repos_excludes_old_pushes():
    recent = _make_repo("recent", pushed_at="2024-05-01T00:00:00Z")
    old = _make_repo("old", pushed_at="2020-01-01T00:00:00Z")

    client = MagicMock()
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = _make_cache(tmp_dir)
        scanner = _make_scanner(client, cache)
        result = scanner._filter_repos([recent, old])

    assert [r.name for r in result] == ["recent"]


def test_filter_repos_includes_repos_with_empty_pushed_at():
    """Repos with no pushed_at should be included (can't determine activity)."""
    repo = _make_repo("nopush", pushed_at="")

    client = MagicMock()
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = _make_cache(tmp_dir)
        scanner = _make_scanner(client, cache)
        result = scanner._filter_repos([repo])

    assert len(result) == 1


# ---------------------------------------------------------------------------
# _scan_repo() — SearchType dispatch
# ---------------------------------------------------------------------------


def _single_indicator_scan(indicator: Indicator, client: MagicMock) -> ScanResult:
    """Helper: scan a single-indicator repo and return the one result."""
    repo = _make_repo("testrepo")
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = _make_cache(tmp_dir)
        scanner = _make_scanner(client, cache, indicators=[indicator])
        results = scanner._scan_repo(repo, "2024-06-01T12:00:00Z")
    assert len(results) == 1
    return results[0]


def test_scan_repo_file_exists_found():
    indicator = Indicator(
        category="claude-code",
        name="CLAUDE.md",
        search_type=SearchType.FILE_EXISTS,
        target="CLAUDE.md",
        description="test",
    )
    client = MagicMock()
    client.check_path_exists.return_value = (True, False)

    result = _single_indicator_scan(indicator, client)

    assert result.found is True
    assert result.file_path == "CLAUDE.md"
    client.check_path_exists.assert_called_once_with("testorg", "testrepo", "CLAUDE.md")


def test_scan_repo_file_exists_not_found():
    indicator = Indicator(
        category="claude-code",
        name="CLAUDE.md",
        search_type=SearchType.FILE_EXISTS,
        target="CLAUDE.md",
        description="test",
    )
    client = MagicMock()
    client.check_path_exists.return_value = (False, False)

    result = _single_indicator_scan(indicator, client)

    assert result.found is False
    assert result.file_path == ""


def test_scan_repo_directory_exists_found():
    indicator = Indicator(
        category="claude-code",
        name=".claude directory",
        search_type=SearchType.DIRECTORY_EXISTS,
        target=".claude",
        description="test",
    )
    client = MagicMock()
    client.check_path_exists.return_value = (True, True)  # exists AND is_dir

    result = _single_indicator_scan(indicator, client)

    assert result.found is True
    assert result.file_path == ".claude"


def test_scan_repo_directory_exists_is_file_not_dir():
    """If path exists but is a file, DIRECTORY_EXISTS should be False."""
    indicator = Indicator(
        category="claude-code",
        name=".claude directory",
        search_type=SearchType.DIRECTORY_EXISTS,
        target=".claude",
        description="test",
    )
    client = MagicMock()
    client.check_path_exists.return_value = (True, False)  # exists but NOT a dir

    result = _single_indicator_scan(indicator, client)

    assert result.found is False


def test_scan_repo_content_search_found():
    indicator = Indicator(
        category="mcp",
        name="mcp in claude settings",
        search_type=SearchType.CONTENT_SEARCH,
        target="mcpServers filename:.claude/settings.json",
        description="test",
    )
    client = MagicMock()
    client.search_code.return_value = SearchResult(
        total_count=2,
        items=[
            {"name": "settings.json", "path": ".claude/settings.json", "html_url": ""},
            {"name": "settings.json", "path": ".claude/settings.local.json", "html_url": ""},
        ],
    )

    result = _single_indicator_scan(indicator, client)

    assert result.found is True
    assert result.details == "2 matches"
    assert ".claude/settings.json" in result.file_path
    assert ".claude/settings.local.json" in result.file_path


def test_scan_repo_content_search_not_found():
    indicator = Indicator(
        category="mcp",
        name="mcp in claude settings",
        search_type=SearchType.CONTENT_SEARCH,
        target="mcpServers filename:.claude/settings.json",
        description="test",
    )
    client = MagicMock()
    client.search_code.return_value = SearchResult(total_count=0, items=[])

    result = _single_indicator_scan(indicator, client)

    assert result.found is False
    assert result.file_path == ""


def test_scan_repo_workflow_search_found():
    indicator = Indicator(
        category="workflows-ai",
        name="claude-code-action",
        search_type=SearchType.WORKFLOW_SEARCH,
        target="claude-code-action",
        description="test",
    )
    client = MagicMock()
    client.search_code_in_workflows.return_value = SearchResult(
        total_count=1,
        items=[{"name": "ci.yml", "path": ".github/workflows/ci.yml", "html_url": ""}],
    )

    result = _single_indicator_scan(indicator, client)

    assert result.found is True
    assert result.details == "1 workflow files"
    assert ".github/workflows/ci.yml" in result.file_path


def test_scan_repo_workflow_search_not_found():
    indicator = Indicator(
        category="workflows-ai",
        name="claude-code-action",
        search_type=SearchType.WORKFLOW_SEARCH,
        target="claude-code-action",
        description="test",
    )
    client = MagicMock()
    client.search_code_in_workflows.return_value = SearchResult(total_count=0, items=[])

    result = _single_indicator_scan(indicator, client)

    assert result.found is False


def test_scan_repo_api_error_does_not_raise():
    """API errors should be logged as warnings, not propagate."""
    indicator = Indicator(
        category="claude-code",
        name="CLAUDE.md",
        search_type=SearchType.FILE_EXISTS,
        target="CLAUDE.md",
        description="test",
    )
    client = MagicMock()
    client.check_path_exists.side_effect = RuntimeError("network error")

    result = _single_indicator_scan(indicator, client)

    assert result.found is False
