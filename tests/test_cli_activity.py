from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from agentic_adoption_scan.cli import main
from agentic_adoption_scan.models import ActivityResult


def _row(org, repo="r1"):
    return ActivityResult("2026-10-07T12:00:00Z", org, repo, "public", "2026-10-05",
                          "claude-code", "commit_trailer", 2, 5)


def _collector_factory(rows_by_org, failing=()):
    def factory(**kwargs):
        org = kwargs["org"]
        c = MagicMock()
        c.failed_repos = []
        if org in failing:
            c.collect.side_effect = RuntimeError("github api error (HTTP 404): Not Found")
        else:
            c.collect.return_value = rows_by_org[org]
        return c

    return factory


def _invoke(tmp_path, args, factory):
    out = tmp_path / "activity.csv"
    with patch("agentic_adoption_scan.activity.ActivityCollector", side_effect=factory), patch(
        "agentic_adoption_scan.github.GitHubClient.from_env", return_value=MagicMock()
    ):
        result = CliRunner().invoke(
            main,
            ["activity", *args, "--output", str(out), "--cache-dir", str(tmp_path / "cache")],
        )
    return result, out


def test_activity_writes_csv_for_all_orgs_and_saves_cache(tmp_path):
    factory = _collector_factory({"orga": [_row("orga")], "orgb": [_row("orgb")]})
    result, out = _invoke(tmp_path, ["--org", "orga", "--org", "orgb"], factory)

    assert result.exit_code == 0, result.output
    lines = out.read_text().splitlines()
    assert lines[0].startswith("scan_timestamp,org,repo,repo_visibility,week_start,tool,signal,count,total_commits")
    assert len(lines) == 3
    assert (tmp_path / "cache" / "activity-state.parquet").exists()
    assert "Activity complete: 2 rows across 2 repos" in result.output


def test_activity_one_failing_org_keeps_others_and_exits_nonzero(tmp_path):
    factory = _collector_factory({"orga": [_row("orga")]}, failing=("orgb",))
    result, out = _invoke(tmp_path, ["--org", "orga", "--org", "orgb"], factory)

    assert result.exit_code == 1
    assert "Failed orgs: orgb" in result.output
    assert ",orga," in out.read_text()


def test_activity_reports_repos_that_failed_to_fetch(tmp_path):
    def factory(**kwargs):
        c = MagicMock()
        c.failed_repos = ["bad-repo"]
        c.collect.return_value = [_row(kwargs["org"])]
        return c

    result, _ = _invoke(tmp_path, ["--org", "orga"], factory)
    assert result.exit_code == 1
    assert "Repos that failed: orga/bad-repo" in result.output


# ---------------------------------------------------------------------------
# Parquet history across runs (real collector + cache, fake GitHub client)
# ---------------------------------------------------------------------------

import glob
from datetime import datetime, timezone

import pyarrow.parquet as pq

from agentic_adoption_scan.activity_cache import ActivityCache
from agentic_adoption_scan.github import Repo
from agentic_adoption_scan.models import CommitInfo

_TRAILER = "feat: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"

# Weeks (Mondays): 07-06, 08-03 and 09-28 are visible in run 1; 10-05 first appears in run 2.
_ALL_COMMITS = [
    CommitInfo("2026-07-08T10:00:00Z", _TRAILER),
    CommitInfo("2026-08-05T10:00:00Z", _TRAILER),
    CommitInfo("2026-10-01T10:00:00Z", "plain commit"),
    CommitInfo("2026-10-08T10:00:00Z", _TRAILER),
]


class _FakeClient:
    def list_org_repos(self, org):
        return [Repo("r1", f"{org}/r1", False, "public", "Python", "2026-10-11T00:00:00Z")]

    def fetch_commits(self, owner, repo, since):
        # Like GitHub history(since=...): only commits at or after `since`, and only ones that exist by "now".
        return [c for c in _ALL_COMMITS if c.committed_date >= since and c.committed_date <= self.now]

    def fetch_pull_activity(self, owner, repo, since):
        return [], []


def _freeze(monkeypatch, moment):
    import agentic_adoption_scan.cli as cli_mod

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    monkeypatch.setattr(cli_mod, "datetime", _Frozen)


def _run_activity(monkeypatch, tmp_path, moment, client):
    _freeze(monkeypatch, moment)
    client.now = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    with patch("agentic_adoption_scan.github.GitHubClient.from_env", return_value=client):
        result = CliRunner().invoke(
            main,
            ["activity", "--org", "orga", "--output", str(tmp_path / "x.parquet"),
             "--cache-dir", str(tmp_path / "cache")],
        )
    assert result.exit_code == 0, result.output


def test_activity_parquet_keeps_weeks_that_slid_out_of_the_window(monkeypatch, tmp_path):
    client = _FakeClient()
    _run_activity(monkeypatch, tmp_path, datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc), client)
    _run_activity(monkeypatch, tmp_path, datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc), client)

    rows = []
    for path in glob.glob(str(tmp_path / "x" / "**" / "*.parquet"), recursive=True):
        rows.extend(pq.ParquetFile(path).read().to_pylist())

    # Run 2's 90-day window starts at week 07-13, so 07-06 exists only in run 1's output.
    assert "2026-07-06" in {r["week_start"] for r in rows}

    # README rule: latest scan per (org, repo, week_start) reconstructs the cache.
    latest = {}
    for r in rows:
        key = (r["org"], r["repo"], r["week_start"])
        latest[key] = max(latest.get(key, ""), r["scan_timestamp"])
    kept = {tuple(r.values()) for r in rows if r["scan_timestamp"] == latest[(r["org"], r["repo"], r["week_start"])]}
    cached = {
        (r.scan_timestamp, r.org, r.repo, r.repo_visibility, r.week_start, r.tool, r.signal, r.count, r.total_commits)
        for r in ActivityCache.load(str(tmp_path / "cache")).rows_for("orga", "r1")
    }
    assert kept == cached
    # Independent expectation: run 2 re-fetches only from the Monday of run 1's fetch time (10-05), so
    # 07-06, 08-03 and 09-28 stay run-1 rows and only 10-05 is a run-2 row.
    assert {(k[2], v) for k, v in latest.items()} == {
        ("2026-07-06", "2026-10-05T12:00:00Z"),
        ("2026-08-03", "2026-10-05T12:00:00Z"),
        ("2026-09-28", "2026-10-05T12:00:00Z"),
        ("2026-10-05", "2026-10-12T12:00:00Z"),
    }
