"""Weekly AI-attribution activity: aggregation and collection.

Rows hold counts only. Commit messages and author logins are read to classify
items and then discarded.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from agentic_adoption_scan.activity_cache import ActivityCache
from agentic_adoption_scan.github import GitHubClient
from agentic_adoption_scan.models import ActivityResult, CommitInfo, PullInfo, ReviewInfo
from agentic_adoption_scan.scanner import filter_repos
from agentic_adoption_scan.signals import ActivityMatchers, bot_tool, match_trailer_tools

logger = logging.getLogger(__name__)


def week_start(ts: str) -> str:
    """Return the UTC Monday (``YYYY-MM-DD``) of the ISO week containing *ts*.

    Timestamps without an offset are read as UTC.
    """
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return (dt - timedelta(days=dt.weekday())).date().isoformat()


def build_activity_rows(
    *,
    org: str,
    repo: str,
    visibility: str,
    scan_timestamp: str,
    commits: list[CommitInfo],
    pulls: list[PullInfo],
    reviews: list[ReviewInfo],
    matchers: ActivityMatchers,
    since_week: str,
) -> list[ActivityResult]:
    """Aggregate raw items into weekly rows for weeks >= *since_week*.

    A week with commits but no AI signal yields one zero row
    (``tool=""``, ``signal="none"``) so the denominator exists.
    """
    totals: dict[str, int] = {}
    counts: dict[tuple[str, str, str], int] = {}

    def bump(week: str, tool: str, signal: str) -> None:
        key = (week, tool, signal)
        counts[key] = counts.get(key, 0) + 1

    for c in commits:
        week = week_start(c.committed_date)
        if week < since_week:
            continue
        totals[week] = totals.get(week, 0) + 1
        for tool in match_trailer_tools(c.message, matchers):
            bump(week, tool, "commit_trailer")

    for p in pulls:
        week = week_start(p.created_at)
        tool = bot_tool(p.author_login, matchers)
        if week >= since_week and tool:
            bump(week, tool, "pr_author_bot")

    for r in reviews:
        week = week_start(r.submitted_at)
        tool = bot_tool(r.author_login, matchers)
        if week >= since_week and tool:
            bump(week, tool, "review_bot")

    weeks_with_signal = {week for (week, _, _) in counts}
    rows: list[ActivityResult] = []
    for (week, tool, signal), count in counts.items():
        rows.append(_row(org, repo, visibility, scan_timestamp, week, tool, signal, count, totals.get(week, 0)))
    for week, total in totals.items():
        if week not in weeks_with_signal:
            rows.append(_row(org, repo, visibility, scan_timestamp, week, "", "none", 0, total))

    rows.sort(key=lambda r: (r.week_start, r.tool, r.signal))
    return rows


def _row(org, repo, visibility, scan_timestamp, week, tool, signal, count, total) -> ActivityResult:
    return ActivityResult(
        scan_timestamp=scan_timestamp,
        org=org,
        repo=repo,
        repo_visibility=visibility,
        week_start=week,
        tool=tool,
        signal=signal,
        count=count,
        total_commits=total,
    )


class ActivityCollector:
    """Collect weekly AI-attribution activity for one org.

    The first fetch of a repo backfills from the Monday of the window start.
    Later fetches re-fetch from the Monday of the week containing the cached
    ``fetched_through`` and replace that week and later, so partial weeks are
    recomputed, not double-counted. A repo whose fetch fails is left untouched
    (and retried next run).
    """

    def __init__(
        self,
        client: GitHubClient,
        cache: ActivityCache,
        org: str,
        matchers: ActivityMatchers,
        active_since: datetime,
        include_archived: bool = False,
        force: bool = False,
        now: Optional[datetime] = None,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.org = org
        self.matchers = matchers
        self.active_since = active_since
        self.include_archived = include_archived
        self.force = force
        self._now = now
        self._log = log or logger
        self.failed_repos: list[str] = []

    def collect(self) -> list[ActivityResult]:
        repos = filter_repos(
            self.client.list_org_repos(self.org), self.active_since, self.include_archived
        )
        self._log.info("Collecting activity for %d repos in %s", len(repos), self.org)

        now = self._now or datetime.now(tz=timezone.utc)
        scan_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        window_week = week_start(self.active_since.isoformat())

        results: list[ActivityResult] = []
        for i, repo in enumerate(repos, start=1):
            self._log.info("[%d/%d] Activity for %s", i, len(repos), repo.full_name)
            through = "" if self.force else self.cache.fetched_through(self.org, repo.name)
            since_week = week_start(through) if through else window_week
            since = f"{since_week}T00:00:00Z"

            try:
                commits = self.client.fetch_commits(self.org, repo.name, since)
                pulls, reviews = self.client.fetch_pull_activity(self.org, repo.name, since)
            except Exception as exc:  # noqa: BLE001
                self._log.warning("  Warning: activity fetch failed for %s: %s", repo.name, exc)
                self.failed_repos.append(repo.name)
            else:
                rows = build_activity_rows(
                    org=self.org,
                    repo=repo.name,
                    visibility=repo.visibility,
                    scan_timestamp=scan_ts,
                    commits=commits,
                    pulls=pulls,
                    reviews=reviews,
                    matchers=self.matchers,
                    since_week=since_week,
                )
                self.cache.replace_from_week(self.org, repo.name, since_week, rows, scan_ts)

            results.extend(
                r for r in self.cache.rows_for(self.org, repo.name) if r.week_start >= window_week
            )

        results.sort(key=lambda r: (r.repo, r.week_start, r.tool, r.signal))
        return results
