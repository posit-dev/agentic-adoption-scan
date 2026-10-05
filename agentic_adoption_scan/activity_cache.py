"""Cache of weekly activity rows plus a per-repo ``fetched_through`` time.

Two Parquet files live next to ``scan-cache.parquet`` in the cache directory:
``activity-cache.parquet`` (rows) and ``activity-state.parquet``
(org, repo, fetched_through).
"""
from __future__ import annotations

import os
import posixpath

from agentic_adoption_scan.models import ActivityResult
from agentic_adoption_scan.parquet_io import (
    read_activity_rows,
    read_activity_state,
    write_activity_rows,
    write_activity_state,
)
from agentic_adoption_scan.storage import LocalStore, ObjectStore, parse_store_path

ROWS_FILE = "activity-cache.parquet"
STATE_FILE = "activity-state.parquet"


class ActivityCache:
    def __init__(
        self,
        cache_dir: str,
        store: ObjectStore,
        base_path: str,
        rows: dict[tuple[str, str], list[ActivityResult]],
        through: dict[tuple[str, str], str],
    ) -> None:
        self._cache_dir = cache_dir
        self._store = store
        self._base_path = base_path
        self._rows = rows
        self._through = through

    @classmethod
    def load(cls, cache_dir: str) -> "ActivityCache":
        store, base_path = parse_store_path(cache_dir)
        rows: dict[tuple[str, str], list[ActivityResult]] = {}
        through: dict[tuple[str, str], str] = {}

        try:
            for r in read_activity_rows(store, posixpath.join(base_path, ROWS_FILE)):
                rows.setdefault((r.org, r.repo), []).append(r)
        except FileNotFoundError:
            pass
        try:
            through = read_activity_state(store, posixpath.join(base_path, STATE_FILE))
        except FileNotFoundError:
            pass
        return cls(cache_dir, store, base_path, rows, through)

    def save(self) -> None:
        if isinstance(self._store, LocalStore):
            os.makedirs(self._cache_dir, exist_ok=True)
        all_rows = [r for rows in self._rows.values() for r in rows]
        write_activity_rows(self._store, posixpath.join(self._base_path, ROWS_FILE), all_rows)
        write_activity_state(self._store, posixpath.join(self._base_path, STATE_FILE), self._through)

    def fetched_through(self, org: str, repo: str) -> str:
        return self._through.get((org, repo), "")

    def rows_for(self, org: str, repo: str) -> list[ActivityResult]:
        return list(self._rows.get((org, repo), []))

    def replace_from_week(
        self,
        org: str,
        repo: str,
        since_week: str,
        new_rows: list[ActivityResult],
        fetched_through: str,
    ) -> None:
        """Replace cached rows for weeks >= *since_week* and record the fetch time.

        Weeks before *since_week* are kept. Replacing (not adding) makes a
        partial-week re-fetch idempotent.
        """
        kept = [r for r in self._rows.get((org, repo), []) if r.week_start < since_week]
        self._rows[(org, repo)] = kept + list(new_rows)
        self._through[(org, repo)] = fetched_through
