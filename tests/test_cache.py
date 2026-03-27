"""Cache round-trip and freshness tests.

Ported from Go's TestCacheRoundTrip in indicators_test.go.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from agentic_adoption_scan.cache import Cache, CachedIndicator
from agentic_adoption_scan.compact import deduplicate_scan_rows
from agentic_adoption_scan.parquet_io import ScanRow


# ---------------------------------------------------------------------------
# Cache round-trip
# ---------------------------------------------------------------------------


def test_cache_round_trip(tmp_path):
    """Save and re-load a cache; verify freshness and indicator data."""
    cache_dir = str(tmp_path)
    store, base_path = _empty_cache(cache_dir)

    cache = Cache(cache_dir, store, base_path, {})
    cache.set_repo_results(
        "org",
        "repo1",
        "2026-01-01T00:00:00Z",
        [
            CachedIndicator(
                category="claude-code",
                indicator="CLAUDE.md",
                found=True,
                file_path="CLAUDE.md",
                details="",
                scanned_at="2026-03-23T00:00:00Z",
            )
        ],
    )
    cache.save()

    loaded = Cache.load_cache(cache_dir)

    assert loaded.is_repo_fresh("org", "repo1", "2026-01-01T00:00:00Z")
    assert not loaded.is_repo_fresh("org", "repo1", "2026-02-01T00:00:00Z")

    results = loaded.get_repo_results("org", "repo1")
    assert results is not None
    assert len(results) == 1
    assert results[0].found is True
    assert results[0].category == "claude-code"
    assert results[0].indicator == "CLAUDE.md"


def test_cache_unknown_repo_returns_none(tmp_path):
    """get_repo_results returns None for repos not in cache."""
    cache = Cache.load_cache(str(tmp_path))
    assert cache.get_repo_results("org", "missing-repo") is None


def test_is_repo_fresh_not_cached(tmp_path):
    """is_repo_fresh returns False for uncached repos."""
    cache = Cache.load_cache(str(tmp_path))
    assert not cache.is_repo_fresh("org", "repo", "2026-01-01T00:00:00Z")


def test_cache_multiple_repos(tmp_path):
    """Multiple repos are independently tracked and retrieved."""
    cache_dir = str(tmp_path)
    store, base_path = _empty_cache(cache_dir)
    cache = Cache(cache_dir, store, base_path, {})

    cache.set_repo_results(
        "myorg",
        "repo-a",
        "pushed-a",
        [CachedIndicator("cat", "ind1", True, "", "", "2026-03-01T00:00:00Z")],
    )
    cache.set_repo_results(
        "myorg",
        "repo-b",
        "pushed-b",
        [CachedIndicator("cat", "ind2", False, "", "", "2026-03-01T00:00:00Z")],
    )
    cache.save()

    loaded = Cache.load_cache(cache_dir)

    assert loaded.is_repo_fresh("myorg", "repo-a", "pushed-a")
    assert loaded.is_repo_fresh("myorg", "repo-b", "pushed-b")
    assert not loaded.is_repo_fresh("myorg", "repo-a", "pushed-b")

    results_a = loaded.get_repo_results("myorg", "repo-a")
    assert results_a is not None and results_a[0].indicator == "ind1"

    results_b = loaded.get_repo_results("myorg", "repo-b")
    assert results_b is not None and results_b[0].indicator == "ind2"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_deduplicate_keeps_latest():
    """deduplicate_scan_rows retains only the most recent scan per org/repo."""
    rows = [
        ScanRow("2026-01-01T00:00:00Z", "org", "repo", "", "", "", "cat", "ind1", True, "", ""),
        ScanRow("2026-01-02T00:00:00Z", "org", "repo", "", "", "", "cat", "ind1", False, "", ""),
        ScanRow("2026-01-02T00:00:00Z", "org", "repo", "", "", "", "cat", "ind2", True, "", ""),
    ]
    deduped = deduplicate_scan_rows(rows)
    assert len(deduped) == 2
    for r in deduped:
        assert r.scan_timestamp == "2026-01-02T00:00:00Z"


def test_deduplicate_multiple_repos():
    """Each (org, repo) pair is independently deduplicated."""
    rows = [
        ScanRow("2026-01-01T00:00:00Z", "org", "repo1", "", "", "", "cat", "ind", True, "", ""),
        ScanRow("2026-01-02T00:00:00Z", "org", "repo1", "", "", "", "cat", "ind", False, "", ""),
        ScanRow("2026-01-01T00:00:00Z", "org", "repo2", "", "", "", "cat", "ind", True, "", ""),
    ]
    deduped = deduplicate_scan_rows(rows)
    assert len(deduped) == 2
    repos = {r.repo for r in deduped}
    assert repos == {"repo1", "repo2"}
    repo1_rows = [r for r in deduped if r.repo == "repo1"]
    assert repo1_rows[0].scan_timestamp == "2026-01-02T00:00:00Z"


def test_deduplicate_empty():
    assert deduplicate_scan_rows([]) == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_cache(cache_dir: str):
    """Return (store, base_path) for a fresh local cache directory."""
    from agentic_adoption_scan.storage import parse_store_path
    return parse_store_path(cache_dir)
