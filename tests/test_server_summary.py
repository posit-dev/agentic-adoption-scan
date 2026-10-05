from __future__ import annotations

from agentic_adoption_scan.cache import CachedIndicator, CachedRepo
from agentic_adoption_scan.models import ScanResult
from agentic_adoption_scan.server import _count_unique_repos, summarize_adoption


def _cached(*found_categories: str) -> CachedRepo:
    return CachedRepo(
        pushed_at="2026-10-01T00:00:00Z",
        scanned_at="2026-10-05T00:00:00Z",
        indicators=[
            CachedIndicator(
                category=c,
                indicator=f"{c}-ind",
                found=True,
                file_path="x",
                details="",
                scanned_at="2026-10-05T00:00:00Z",
            )
            for c in found_categories
        ],
    )


def test_summary_keeps_same_named_repos_in_different_orgs_separate():
    data = {
        "orga/vip": _cached("claude-code", "mcp"),
        "orgb/vip": _cached("cursor"),
    }
    summary = summarize_adoption(data, ["orga", "orgb"])

    assert summary["orgs"] == ["orga", "orgb"]
    assert summary["org"] == "orga,orgb"
    assert summary["total_repos"] == 2
    assert summary["repos_with_any_indicator"] == 2
    top = {(r["org"], r["repo"]): r["indicator_count"] for r in summary["top_repos"]}
    assert top == {("orga", "vip"): 2, ("orgb", "vip"): 1}


def test_summary_org_prefix_does_not_match_longer_org_names():
    data = {"posit/a": _cached("mcp"), "posit-dev/b": _cached("mcp")}
    summary = summarize_adoption(data, ["posit"])
    assert summary["total_repos"] == 1


def test_count_unique_repos_distinguishes_orgs():
    def r(org):
        return ScanResult("t", org, "vip", "", "", "", "c", "i", True, "", "")

    assert _count_unique_repos([r("orga"), r("orgb")]) == 2
