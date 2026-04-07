"""Scanner: orchestrates scanning a GitHub org for agentic adoption indicators.

Port of agentic-adoption-scan/scanner.go.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from agentic_adoption_scan.cache import Cache, CachedIndicator
from agentic_adoption_scan.github import GitHubClient, Repo
from agentic_adoption_scan.indicators import Indicator, SearchType
from agentic_adoption_scan.models import ScanResult

logger = logging.getLogger(__name__)


class Scanner:
    """Orchestrates the full org scan.

    Parameters
    ----------
    client:
        Authenticated GitHub client.
    cache:
        Persistent result cache.
    org:
        GitHub organisation slug to scan.
    indicators:
        List of indicators to check per repo.
    active_since:
        Exclude repos whose last push is before this datetime.
    include_archived:
        When False (default), skip archived repos.
    force:
        When True, bypass the cache and re-scan every repo.
    log:
        Optional logger; defaults to the module logger.
    """

    def __init__(
        self,
        client: GitHubClient,
        cache: Cache,
        org: str,
        indicators: list[Indicator],
        active_since: datetime,
        include_archived: bool = False,
        force: bool = False,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.org = org
        self.indicators = indicators
        self.active_since = active_since
        self.include_archived = include_archived
        self.force = force
        self._log = log or logger

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def scan(self) -> list[ScanResult]:
        """Run the full scan and return tidy results."""
        repos = self.client.list_org_repos(self.org)
        filtered = self._filter_repos(repos)
        self._log.info(
            "Scanning %d repos (filtered from %d total)", len(filtered), len(repos)
        )

        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        results: list[ScanResult] = []

        for i, repo in enumerate(filtered, start=1):
            self._log.info("[%d/%d] Scanning %s", i, len(filtered), repo.full_name)

            # Cache hit: reuse stored results
            if not self.force and self.cache.is_repo_fresh(
                self.org, repo.name, repo.pushed_at
            ):
                self._log.info(
                    "  Cache hit for %s (pushed_at unchanged)", repo.name
                )
                cached = self.cache.get_repo_results(self.org, repo.name) or []
                for cr in cached:
                    results.append(
                        ScanResult(
                            scan_timestamp=cr.scanned_at,
                            org=self.org,
                            repo=repo.name,
                            repo_visibility=repo.visibility,
                            repo_language=repo.language,
                            repo_pushed_at=repo.pushed_at,
                            category=cr.category,
                            indicator=cr.indicator,
                            found=cr.found,
                            file_path=cr.file_path,
                            details=cr.details,
                        )
                    )
                continue

            repo_results = self._scan_repo(repo, now)
            results.extend(repo_results)

            # Update cache
            cache_indicators = [
                CachedIndicator(
                    category=r.category,
                    indicator=r.indicator,
                    found=r.found,
                    file_path=r.file_path,
                    details=r.details,
                    scanned_at=r.scan_timestamp,
                )
                for r in repo_results
            ]
            self.cache.set_repo_results(
                self.org, repo.name, repo.pushed_at, cache_indicators
            )

        return results

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _filter_repos(self, repos: list[Repo]) -> list[Repo]:
        """Drop archived repos (unless include_archived) and inactive repos."""
        filtered: list[Repo] = []
        for repo in repos:
            if repo.archived and not self.include_archived:
                continue
            if repo.pushed_at:
                try:
                    pushed = datetime.fromisoformat(
                        repo.pushed_at.replace("Z", "+00:00")
                    )
                    # Make active_since offset-aware if it isn't already
                    since = self.active_since
                    if since.tzinfo is None:
                        since = since.replace(tzinfo=timezone.utc)
                    if pushed < since:
                        continue
                except ValueError:
                    pass  # can't parse; include the repo
            filtered.append(repo)
        return filtered

    # ------------------------------------------------------------------
    # Per-repo scanning
    # ------------------------------------------------------------------

    def _scan_repo(self, repo: Repo, timestamp: str) -> list[ScanResult]:
        """Check every indicator against *repo*. Returns one result per indicator."""
        owner = self.org
        results: list[ScanResult] = []

        for ind in self.indicators:
            result = ScanResult(
                scan_timestamp=timestamp,
                org=self.org,
                repo=repo.name,
                repo_visibility=repo.visibility,
                repo_language=repo.language,
                repo_pushed_at=repo.pushed_at,
                category=ind.category,
                indicator=ind.name,
                found=False,
                file_path="",
                details="",
            )

            if ind.search_type == SearchType.FILE_EXISTS:
                try:
                    exists, _ = self.client.check_path_exists(owner, repo.name, ind.target)
                except Exception as exc:  # noqa: BLE001
                    self._log.warning(
                        "  Warning: error checking %s in %s: %s",
                        ind.target,
                        repo.name,
                        exc,
                    )
                    exists = False
                result.found = exists
                if exists:
                    result.file_path = ind.target

            elif ind.search_type == SearchType.DIRECTORY_EXISTS:
                try:
                    exists, is_dir = self.client.check_path_exists(
                        owner, repo.name, ind.target
                    )
                except Exception as exc:  # noqa: BLE001
                    self._log.warning(
                        "  Warning: error checking %s in %s: %s",
                        ind.target,
                        repo.name,
                        exc,
                    )
                    exists, is_dir = False, False
                result.found = exists and is_dir
                if result.found:
                    result.file_path = ind.target

            elif ind.search_type == SearchType.CONTENT_SEARCH:
                try:
                    sr = self.client.search_code(owner, repo.name, ind.target)
                except Exception as exc:  # noqa: BLE001
                    self._log.warning(
                        "  Warning: error searching %s in %s: %s",
                        ind.target,
                        repo.name,
                        exc,
                    )
                    sr = None
                if sr is not None and sr.total_count > 0:
                    result.found = True
                    result.file_path = "; ".join(
                        item["path"] for item in sr.items
                    )
                    result.details = f"{sr.total_count} matches"

            elif ind.search_type == SearchType.WORKFLOW_SEARCH:
                try:
                    sr = self.client.search_code_in_workflows(
                        owner, repo.name, ind.target
                    )
                except Exception as exc:  # noqa: BLE001
                    self._log.warning(
                        "  Warning: error searching workflows in %s: %s",
                        repo.name,
                        exc,
                    )
                    sr = None
                if sr is not None and sr.total_count > 0:
                    result.found = True
                    result.file_path = "; ".join(
                        item["path"] for item in sr.items
                    )
                    result.details = f"{sr.total_count} workflow files"

            if result.found:
                self._log.info("  Found: %s/%s", ind.category, ind.name)

            results.append(result)

        return results
