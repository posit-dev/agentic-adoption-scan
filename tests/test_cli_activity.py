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
