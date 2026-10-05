from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from agentic_adoption_scan.activity import ActivityCollector
from agentic_adoption_scan.activity_cache import ActivityCache
from agentic_adoption_scan.github import Repo
from agentic_adoption_scan.models import CommitInfo
from agentic_adoption_scan.signals import default_matchers

CLAUDE = "Co-Authored-By: Claude <noreply@anthropic.com>"
WED = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)  # week of 2026-10-05
THU = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _repo(name="r1", pushed="2026-10-06T00:00:00Z", archived=False):
    return Repo(name=name, full_name=f"orga/{name}", archived=archived,
                visibility="public", language="Python", pushed_at=pushed)


def _client(commits_by_repo, repos):
    """Fake client whose fetch_commits honours `since`, like the real API."""
    client = MagicMock()
    client.list_org_repos.return_value = repos
    client.fetch_commits.side_effect = lambda owner, repo, since: [
        c for c in commits_by_repo.get(repo, []) if c.committed_date >= since
    ]
    client.fetch_pull_activity.return_value = ([], [])
    return client


def _collector(client, cache, now, days=14, force=False):
    return ActivityCollector(
        client=client,
        cache=cache,
        org="orga",
        matchers=default_matchers(),
        active_since=WED - timedelta(days=days),  # fixed cutoff, independent of `now`
        force=force,
        now=now,
    )


def _summary(rows):
    return sorted((r.week_start, r.tool, r.signal, r.count, r.total_commits) for r in rows)


def test_first_run_backfills_from_the_monday_of_the_window_start(tmp_path):
    client = _client({"r1": []}, [_repo()])
    _collector(client, ActivityCache.load(str(tmp_path)), WED, days=14).collect()
    # window start = 2026-09-23 (Wed) -> Monday 2026-09-21
    client.fetch_commits.assert_called_once_with("orga", "r1", "2026-09-21T00:00:00Z")
    client.fetch_pull_activity.assert_called_once_with("orga", "r1", "2026-09-21T00:00:00Z")


def test_rerun_mid_week_replaces_the_partial_week_instead_of_double_counting(tmp_path):
    commits = {"r1": [CommitInfo("2026-10-06T10:00:00Z", f"a\n\n{CLAUDE}")]}
    cache = ActivityCache.load(str(tmp_path))
    client = _client(commits, [_repo()])

    first = _collector(client, cache, WED).collect()
    assert _summary(first) == [("2026-10-05", "claude-code", "commit_trailer", 1, 1)]

    commits["r1"].append(CommitInfo("2026-10-08T09:00:00Z", "plain follow-up"))
    second = _collector(client, cache, THU).collect()

    # second run re-fetched from the Monday of the week containing fetched_through
    assert client.fetch_commits.call_args.args == ("orga", "r1", "2026-10-05T00:00:00Z")
    assert _summary(second) == [("2026-10-05", "claude-code", "commit_trailer", 1, 2)]


def test_identical_rerun_yields_identical_rows(tmp_path):
    commits = {"r1": [CommitInfo("2026-10-06T10:00:00Z", f"a\n\n{CLAUDE}")]}
    cache = ActivityCache.load(str(tmp_path))
    client = _client(commits, [_repo()])
    first = _summary(_collector(client, cache, WED).collect())
    second = _summary(_collector(client, cache, WED).collect())
    assert first == second


def test_earlier_weeks_survive_an_incremental_run(tmp_path):
    commits = {"r1": [CommitInfo("2026-09-29T10:00:00Z", f"old\n\n{CLAUDE}")]}
    cache = ActivityCache.load(str(tmp_path))
    client = _client(commits, [_repo()])
    _collector(client, cache, WED).collect()

    # the old commit is now outside the incremental fetch window
    rows = _collector(client, cache, THU).collect()
    assert ("2026-09-28", "claude-code", "commit_trailer", 1, 1) in _summary(rows)


def test_empty_repo_yields_no_rows_but_is_marked_fetched(tmp_path):
    cache = ActivityCache.load(str(tmp_path))
    client = _client({}, [_repo("empty")])
    assert _collector(client, cache, WED).collect() == []
    assert cache.fetched_through("orga", "empty") == "2026-10-07T12:00:00Z"


def test_failing_repo_is_skipped_retried_and_does_not_stop_others(tmp_path):
    commits = {"good": [CommitInfo("2026-10-06T10:00:00Z", f"a\n\n{CLAUDE}")]}
    cache = ActivityCache.load(str(tmp_path))
    client = _client(commits, [_repo("bad"), _repo("good")])
    original = client.fetch_commits.side_effect

    def flaky(owner, repo, since):
        if repo == "bad":
            raise RuntimeError("github graphql error: boom")
        return original(owner, repo, since)

    client.fetch_commits.side_effect = flaky
    collector = _collector(client, cache, WED)
    rows = collector.collect()

    assert collector.failed_repos == ["bad"]
    assert {r.repo for r in rows} == {"good"}
    assert cache.fetched_through("orga", "bad") == ""  # will do a full backfill next run


def test_archived_and_inactive_repos_are_skipped(tmp_path):
    repos = [_repo("live"), _repo("old", pushed="2026-01-01T00:00:00Z"), _repo("arch", archived=True)]
    client = _client({}, repos)
    _collector(client, ActivityCache.load(str(tmp_path)), WED).collect()
    assert [c.args[1] for c in client.fetch_commits.call_args_list] == ["live"]


def test_force_backfills_the_full_window_even_when_cached(tmp_path):
    cache = ActivityCache.load(str(tmp_path))
    client = _client({"r1": []}, [_repo()])
    _collector(client, cache, WED).collect()
    _collector(client, cache, THU, force=True).collect()
    assert client.fetch_commits.call_args.args == ("orga", "r1", "2026-09-21T00:00:00Z")
