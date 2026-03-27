"""Scan result cache backed by a flat Parquet file.

Reads scan-cache.parquet from the cache directory. Falls back to reading
scan-cache.json for local stores (legacy migration path).
"""
from __future__ import annotations

import json
import os
import posixpath
from dataclasses import dataclass, field

from agentic_adoption_scan.parquet_io import (
    ScanRow,
    read_scan_rows,
    write_scan_rows,
)
from agentic_adoption_scan.storage import LocalStore, ObjectStore, parse_store_path


# ---------------------------------------------------------------------------
# Cache data types
# ---------------------------------------------------------------------------


@dataclass
class CachedIndicator:
    category: str
    indicator: str
    found: bool
    file_path: str
    details: str
    scanned_at: str


@dataclass
class CachedRepo:
    pushed_at: str
    scanned_at: str
    indicators: list[CachedIndicator] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Conversion helpers (CacheData <-> []ScanRow)
# ---------------------------------------------------------------------------

CacheData = dict[str, CachedRepo]  # key: "org/repo"


def _cache_data_from_rows(rows: list[ScanRow]) -> CacheData:
    """Build in-memory cache from flat ScanRows, keeping only the latest scan per repo."""
    latest: dict[str, str] = {}
    for r in rows:
        key = f"{r.org}/{r.repo}"
        if r.scan_timestamp > latest.get(key, ""):
            latest[key] = r.scan_timestamp

    data: CacheData = {}
    for r in rows:
        key = f"{r.org}/{r.repo}"
        if r.scan_timestamp != latest.get(key):
            continue
        if key not in data:
            data[key] = CachedRepo(pushed_at=r.repo_pushed_at, scanned_at=r.scan_timestamp)
        data[key].indicators.append(CachedIndicator(
            category=r.category,
            indicator=r.indicator,
            found=r.found,
            file_path=r.file_path,
            details=r.details,
            scanned_at=r.scan_timestamp,
        ))
    return data


def _cache_data_to_rows(data: CacheData) -> list[ScanRow]:
    """Convert in-memory cache to a flat list of ScanRows."""
    rows: list[ScanRow] = []
    for key, cached in data.items():
        parts = key.split("/", 1)
        if len(parts) != 2:
            continue
        org, repo = parts
        for ind in cached.indicators:
            rows.append(ScanRow(
                scan_timestamp=ind.scanned_at,
                org=org,
                repo=repo,
                repo_visibility="",
                repo_language="",
                repo_pushed_at=cached.pushed_at,
                category=ind.category,
                indicator=ind.indicator,
                found=ind.found,
                file_path=ind.file_path,
                details=ind.details,
            ))
    return rows


def _load_legacy_json(path: str) -> CacheData | None:
    """Read legacy JSON cache file. Returns None if file missing or invalid."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    data: CacheData = {}
    for key, entry in raw.items():
        indicators = [
            CachedIndicator(
                category=ind.get("category", ""),
                indicator=ind.get("indicator", ""),
                found=bool(ind.get("found", False)),
                file_path=ind.get("file_path", ""),
                details=ind.get("details", ""),
                scanned_at=ind.get("scanned_at", ""),
            )
            for ind in entry.get("indicators", [])
        ]
        data[key] = CachedRepo(
            pushed_at=entry.get("pushed_at", ""),
            scanned_at=entry.get("scanned_at", ""),
            indicators=indicators,
        )
    return data


# ---------------------------------------------------------------------------
# Cache class
# ---------------------------------------------------------------------------


class Cache:
    def __init__(self, cache_dir: str, store: ObjectStore, base_path: str, data: CacheData) -> None:
        self._cache_dir = cache_dir
        self._store = store
        self._base_path = base_path
        self._data = data

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load_cache(cls, cache_dir: str) -> "Cache":
        """Load cache from *cache_dir*.

        Tries scan-cache.parquet first; falls back to scan-cache.json for
        local stores.
        """
        store, base_path = parse_store_path(cache_dir)
        parquet_path = posixpath.join(base_path, "scan-cache.parquet")

        try:
            rows = read_scan_rows(store, parquet_path)
            data = _cache_data_from_rows(rows)
            return cls(cache_dir, store, base_path, data)
        except FileNotFoundError:
            pass
        except Exception as exc:
            raise RuntimeError(f"loading parquet cache: {exc}") from exc

        # Fallback: legacy JSON (local only)
        data: CacheData = {}
        if isinstance(store, LocalStore):
            json_path = os.path.join(cache_dir, "scan-cache.json")
            legacy = _load_legacy_json(json_path)
            if legacy is not None:
                data = legacy

        return cls(cache_dir, store, base_path, data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist cache to <cache_dir>/scan-cache.parquet."""
        if isinstance(self._store, LocalStore):
            os.makedirs(self._cache_dir, exist_ok=True)

        rows = _cache_data_to_rows(self._data)
        parquet_path = posixpath.join(self._base_path, "scan-cache.parquet")
        write_scan_rows(self._store, parquet_path, rows)

    # ------------------------------------------------------------------
    # Query / mutation
    # ------------------------------------------------------------------

    def is_repo_fresh(self, org: str, repo: str, pushed_at: str) -> bool:
        """Return True if the repo's pushed_at matches the cached value."""
        key = f"{org}/{repo}"
        cached = self._data.get(key)
        if cached is None:
            return False
        return cached.pushed_at == pushed_at

    def get_repo_results(self, org: str, repo: str) -> list[CachedIndicator] | None:
        """Return cached indicators for a repo, or None if not cached."""
        key = f"{org}/{repo}"
        cached = self._data.get(key)
        if cached is None:
            return None
        return cached.indicators

    def set_repo_results(
        self,
        org: str,
        repo: str,
        pushed_at: str,
        indicators: list[CachedIndicator],
    ) -> None:
        """Update the cache for a repo."""
        key = f"{org}/{repo}"
        scanned_at = indicators[0].scanned_at if indicators else ""
        self._data[key] = CachedRepo(
            pushed_at=pushed_at,
            scanned_at=scanned_at,
            indicators=indicators,
        )
