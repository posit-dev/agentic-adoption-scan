"""Inspector: fetches and summarizes content for found indicators.

Port of agentic-adoption-scan/inspect.go.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from agentic_adoption_scan.github import GitHubClient
from agentic_adoption_scan.models import InspectResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal data type
# ---------------------------------------------------------------------------


class _FoundEntry:
    __slots__ = ("repo", "category", "indicator", "file_path")

    def __init__(
        self, repo: str, category: str, indicator: str, file_path: str
    ) -> None:
        self.repo = repo
        self.category = category
        self.indicator = indicator
        self.file_path = file_path


# ---------------------------------------------------------------------------
# Inspector
# ---------------------------------------------------------------------------


class Inspector:
    """Reads scan results and fetches raw content for found indicators.

    Parameters
    ----------
    client:
        Authenticated GitHub client.
    org:
        GitHub organisation slug (owner for API calls).
    log:
        Optional logger; defaults to the module logger.
    """

    def __init__(
        self,
        client: GitHubClient,
        org: str,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.client = client
        self.org = org
        self._log = log or logger

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def inspect(self, scan_results_path: str) -> list[InspectResult]:
        """Read *scan_results_path* (CSV or Parquet) and fetch content.

        Only entries where ``found=true`` and ``file_path`` is non-empty are
        processed.  File paths that contain multiple paths separated by ``"; "``
        are split and each path is fetched individually.
        """
        entries = self._read_found_indicators(scan_results_path)
        self._log.info("Found %d indicators to inspect", len(entries))

        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        results: list[InspectResult] = []

        for i, entry in enumerate(entries, start=1):
            self._log.info(
                "[%d/%d] Inspecting %s/%s: %s",
                i,
                len(entries),
                entry.repo,
                entry.file_path,
                entry.indicator,
            )

            paths = [p.strip() for p in entry.file_path.split(";") if p.strip()]
            for path in paths:
                try:
                    content = self.client.get_file_content(self.org, entry.repo, path)
                except Exception as exc:  # noqa: BLE001
                    self._log.warning(
                        "  Warning: could not fetch %s/%s/%s: %s",
                        self.org,
                        entry.repo,
                        path,
                        exc,
                    )
                    continue

                summary = summarize_content(
                    entry.category, entry.indicator, content.decode(errors="replace")
                )
                results.append(
                    InspectResult(
                        scan_timestamp=now,
                        org=self.org,
                        repo=entry.repo,
                        category=entry.category,
                        indicator=entry.indicator,
                        file_path=path,
                        content_size=len(content),
                        content_summary=summary,
                        raw_content=content.decode(errors="replace"),
                    )
                )

        return results

    # ------------------------------------------------------------------
    # Reading found indicators
    # ------------------------------------------------------------------

    def _read_found_indicators(self, path: str) -> list[_FoundEntry]:
        """Detect CSV vs Parquet and read entries where found=true."""
        if path.endswith(".parquet") or _is_parquet_dir(path):
            return _read_found_indicators_parquet(path)
        return _read_found_indicators_csv(path)


# ---------------------------------------------------------------------------
# CSV reader
# ---------------------------------------------------------------------------


def _read_found_indicators_csv(path: str) -> list[_FoundEntry]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"repo", "category", "indicator", "found", "file_path"}
        entries: list[_FoundEntry] = []
        for row in reader:
            if not required.issubset(row.keys()):
                raise ValueError(
                    f"CSV missing required columns: {required - set(row.keys())}"
                )
            if row["found"].lower() != "true":
                continue
            fp = row["file_path"].strip()
            if not fp:
                continue
            entries.append(
                _FoundEntry(
                    repo=row["repo"],
                    category=row["category"],
                    indicator=row["indicator"],
                    file_path=fp,
                )
            )
    return entries


# ---------------------------------------------------------------------------
# Parquet reader
# ---------------------------------------------------------------------------


def _is_parquet_dir(path: str) -> bool:
    """Return True if *path* is a directory (assumed to contain Parquet files)."""
    return os.path.isdir(path)


def _read_found_indicators_parquet(path: str) -> list[_FoundEntry]:
    """Read found indicators from a single Parquet file or a partitioned directory."""
    from agentic_adoption_scan.parquet_io import read_scan_rows
    from agentic_adoption_scan.storage import LocalStore

    store = LocalStore()

    if _is_parquet_dir(path):
        parquet_files = store.list(path)
        rows = []
        for f in parquet_files:
            rows.extend(read_scan_rows(store, f))
    else:
        rows = read_scan_rows(store, path)

    entries: list[_FoundEntry] = []
    for row in rows:
        if not row.found or not row.file_path:
            continue
        entries.append(
            _FoundEntry(
                repo=row.repo,
                category=row.category,
                indicator=row.indicator,
                file_path=row.file_path,
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Summarize content
# ---------------------------------------------------------------------------


def summarize_content(category: str, indicator: str, content: str) -> str:
    """Produce a short human-readable summary of *content*.

    Dispatches on *category* (and *indicator* for claude-code).
    """
    if category == "mcp":
        return _summarize_mcp(content)
    if category == "evals":
        return _summarize_evals(indicator, content)
    if category == "claude-code" and indicator in ("CLAUDE.md", "AGENTS.md"):
        return _summarize_markdown(content)
    return f"{len(content.encode())} bytes"


def _summarize_mcp(content: str) -> str:
    """Extract server names from JSON keys in an MCP config."""
    servers: list[str] = []
    for line in content.splitlines():
        trimmed = line.strip()
        if ":" not in trimmed or "mcpServers" in trimmed:
            continue
        name_part, _ = trimmed.split(":", 1)
        name = name_part.strip().strip('"')
        if name and not name.startswith("//") and not name.startswith("{"):
            servers.append(name)
    if servers:
        return "servers: " + ", ".join(servers)
    return f"{len(content.encode())} bytes"


def _summarize_evals(indicator: str, content: str) -> str:  # noqa: ARG001
    """Return line count for eval files."""
    return f"{len(content.splitlines())} lines"


def _summarize_markdown(content: str) -> str:
    """Return the first five headings, or line count if none found."""
    headings = [
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith("#")
    ]
    if headings:
        return "headings: " + "; ".join(headings[:5])
    return f"{len(content.splitlines())} lines"
