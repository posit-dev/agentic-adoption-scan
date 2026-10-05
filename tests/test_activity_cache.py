from __future__ import annotations

from agentic_adoption_scan.activity_cache import ActivityCache
from agentic_adoption_scan.models import ActivityResult


def _row(week, count=1, org="orga", repo="r1", tool="claude-code", signal="commit_trailer"):
    return ActivityResult("2026-10-05T00:00:00Z", org, repo, "public", week, tool, signal, count, 10)


def test_load_from_empty_dir_is_empty(tmp_path):
    cache = ActivityCache.load(str(tmp_path / "missing"))
    assert cache.fetched_through("orga", "r1") == ""
    assert cache.rows_for("orga", "r1") == []


def test_replace_from_week_keeps_earlier_weeks_and_replaces_later(tmp_path):
    cache = ActivityCache.load(str(tmp_path))
    cache.replace_from_week(
        "orga", "r1", "2026-09-21",
        [_row("2026-09-21", 1), _row("2026-09-28", 2), _row("2026-10-05", 3)],
        "2026-10-07T12:00:00Z",
    )
    cache.replace_from_week(
        "orga", "r1", "2026-10-05",
        [_row("2026-10-05", 9)],
        "2026-10-09T12:00:00Z",
    )
    assert [(r.week_start, r.count) for r in cache.rows_for("orga", "r1")] == [
        ("2026-09-21", 1),
        ("2026-09-28", 2),
        ("2026-10-05", 9),
    ]
    assert cache.fetched_through("orga", "r1") == "2026-10-09T12:00:00Z"


def test_replace_with_no_rows_still_marks_repo_fetched(tmp_path):
    cache = ActivityCache.load(str(tmp_path))
    cache.replace_from_week("orga", "empty", "2026-09-21", [], "2026-10-07T12:00:00Z")
    assert cache.rows_for("orga", "empty") == []
    assert cache.fetched_through("orga", "empty") == "2026-10-07T12:00:00Z"


def test_same_repo_name_in_two_orgs_is_kept_separate(tmp_path):
    cache = ActivityCache.load(str(tmp_path))
    cache.replace_from_week("orga", "vip", "2026-09-28", [_row("2026-09-28", 1, org="orga", repo="vip")], "t1")
    cache.replace_from_week("orgb", "vip", "2026-09-28", [_row("2026-09-28", 5, org="orgb", repo="vip")], "t2")
    assert cache.rows_for("orga", "vip")[0].count == 1
    assert cache.rows_for("orgb", "vip")[0].count == 5


def test_save_and_reload_round_trip(tmp_path):
    cache = ActivityCache.load(str(tmp_path))
    cache.replace_from_week("orga", "r1", "2026-09-28", [_row("2026-09-28", 4)], "2026-10-07T12:00:00Z")
    cache.replace_from_week("orga", "empty", "2026-09-28", [], "2026-10-07T12:00:00Z")
    cache.save()

    loaded = ActivityCache.load(str(tmp_path))
    assert loaded.rows_for("orga", "r1") == cache.rows_for("orga", "r1")
    assert loaded.fetched_through("orga", "r1") == "2026-10-07T12:00:00Z"
    assert loaded.fetched_through("orga", "empty") == "2026-10-07T12:00:00Z"
