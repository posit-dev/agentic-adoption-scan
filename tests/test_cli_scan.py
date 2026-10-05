"""CLI scan tests for multi-org behavior, with Scanner and GitHubClient mocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from agentic_adoption_scan.cli import main
from agentic_adoption_scan.models import ScanResult


def _result(org: str, repo: str) -> ScanResult:
    return ScanResult(
        scan_timestamp="2026-10-05T00:00:00Z",
        org=org,
        repo=repo,
        repo_visibility="public",
        repo_language="Python",
        repo_pushed_at="2026-10-01T00:00:00Z",
        category="claude-code",
        indicator="CLAUDE.md",
        found=True,
        file_path="CLAUDE.md",
        details="",
    )


def _scanner_factory(results_by_org: dict, failing: tuple = ()):
    def factory(**kwargs):
        org = kwargs["org"]
        scanner = MagicMock()
        if org in failing:
            scanner.scan.side_effect = RuntimeError("github api error (HTTP 404): Not Found")
        else:
            scanner.scan.return_value = results_by_org[org]
        return scanner

    return factory


def _invoke(tmp_path, args, factory):
    out = tmp_path / "out.csv"
    with patch("agentic_adoption_scan.scanner.Scanner", side_effect=factory), patch(
        "agentic_adoption_scan.github.GitHubClient.from_env", return_value=MagicMock()
    ):
        result = CliRunner().invoke(
            main,
            ["scan", *args, "--output", str(out), "--cache-dir", str(tmp_path / "cache")],
        )
    return result, out


def test_scan_two_orgs_with_same_repo_name_counts_both(tmp_path):
    factory = _scanner_factory(
        {"orga": [_result("orga", "vip")], "orgb": [_result("orgb", "vip")]}
    )
    result, out = _invoke(tmp_path, ["--org", "orga", "--org", "orgb"], factory)

    assert result.exit_code == 0, result.output
    assert "2 results across 2 repos" in result.output
    rows = out.read_text().splitlines()
    assert len(rows) == 3  # header + one row per org
    assert any(",orga,vip," in r for r in rows)
    assert any(",orgb,vip," in r for r in rows)


def test_scan_one_failing_org_still_writes_others_and_exits_nonzero(tmp_path):
    factory = _scanner_factory({"orga": [_result("orga", "r1")]}, failing=("orgb",))
    result, out = _invoke(tmp_path, ["--org", "orga", "--org", "orgb"], factory)

    assert result.exit_code == 1
    assert "Error scanning orgb" in result.output
    assert "Failed orgs: orgb" in result.output
    assert ",orga,r1," in out.read_text()


def test_scan_all_orgs_failing_exits_nonzero_without_output(tmp_path):
    factory = _scanner_factory({}, failing=("orga",))
    result, out = _invoke(tmp_path, ["--org", "orga"], factory)

    assert result.exit_code == 1
    assert not out.exists()


def test_scan_without_any_org_is_an_error(tmp_path):
    result, _ = _invoke(tmp_path, [], _scanner_factory({}))
    assert result.exit_code == 1
    assert "--org" in result.output


def test_scan_reads_orgs_file(tmp_path):
    f = tmp_path / "orgs.txt"
    f.write_text("orga\norgb\n")
    factory = _scanner_factory(
        {"orga": [_result("orga", "r1")], "orgb": [_result("orgb", "r2")]}
    )
    result, out = _invoke(tmp_path, ["--orgs-file", str(f)], factory)
    assert result.exit_code == 0, result.output
    assert "2 results across 2 repos" in result.output
