"""Weekly AI-attribution activity: aggregation and collection.

Rows hold counts only. Commit messages and author logins are read to classify
items and then discarded.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agentic_adoption_scan.models import ActivityResult, CommitInfo, PullInfo, ReviewInfo
from agentic_adoption_scan.signals import ActivityMatchers, bot_tool, match_trailer_tools


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
