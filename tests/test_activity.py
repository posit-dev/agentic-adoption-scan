from __future__ import annotations

import pytest

from agentic_adoption_scan.activity import build_activity_rows, week_start
from agentic_adoption_scan.models import CommitInfo, PullInfo, ReviewInfo
from agentic_adoption_scan.signals import default_matchers

CLAUDE = "Co-Authored-By: Claude <noreply@anthropic.com>"
COPILOT = "Co-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>"


@pytest.mark.parametrize(
    "ts, expected",
    [
        ("2026-09-28T00:00:00Z", "2026-09-28"),  # Monday 00:00 UTC
        ("2026-10-04T23:59:59Z", "2026-09-28"),  # Sunday 23:59 UTC
        ("2026-10-05T00:00:00Z", "2026-10-05"),  # next Monday
        ("2026-09-27T23:30:00-05:00", "2026-09-28"),  # Sunday evening local, Monday in UTC
        ("2026-09-28T00:30:00+02:00", "2026-09-21"),  # Monday local, still Sunday in UTC
        ("2026-09-30T12:00:00", "2026-09-28"),  # naive timestamps are read as UTC
    ],
)
def test_week_start_is_the_utc_monday(ts, expected):
    assert week_start(ts) == expected


def _build(commits=(), pulls=(), reviews=(), since_week="2026-09-28"):
    return build_activity_rows(
        org="orga",
        repo="r1",
        visibility="public",
        scan_timestamp="2026-10-07T12:00:00Z",
        commits=list(commits),
        pulls=list(pulls),
        reviews=list(reviews),
        matchers=default_matchers(),
        since_week=since_week,
    )


def _key(r):
    return (r.week_start, r.tool, r.signal, r.count, r.total_commits)


def test_all_signals_in_one_week():
    rows = _build(
        commits=[
            CommitInfo("2026-09-29T10:00:00Z", f"a\n\n{CLAUDE}"),
            CommitInfo("2026-09-30T10:00:00Z", f"b\n\n{CLAUDE}\n{COPILOT}"),
            CommitInfo("2026-10-01T10:00:00Z", "c: plain commit"),
        ],
        pulls=[PullInfo("2026-09-29T09:00:00Z", "Copilot")],
        reviews=[ReviewInfo("2026-09-30T09:00:00Z", "copilot-pull-request-reviewer")],
    )
    assert [_key(r) for r in rows] == [
        ("2026-09-28", "claude-code", "commit_trailer", 2, 3),
        ("2026-09-28", "copilot", "commit_trailer", 1, 3),
        ("2026-09-28", "copilot", "pr_author_bot", 1, 3),
        ("2026-09-28", "copilot", "review_bot", 1, 3),
    ]
    assert all(r.org == "orga" and r.repo == "r1" and r.repo_visibility == "public" for r in rows)
    assert all(r.scan_timestamp == "2026-10-07T12:00:00Z" for r in rows)


def test_week_with_commits_but_no_ai_gets_a_zero_row():
    rows = _build(
        commits=[
            CommitInfo("2026-10-06T10:00:00Z", "plain one"),
            CommitInfo("2026-10-07T10:00:00Z", "plain two"),
        ]
    )
    assert [_key(r) for r in rows] == [("2026-10-05", "", "none", 0, 2)]


def test_week_with_only_a_bot_pr_has_zero_total_commits():
    rows = _build(pulls=[PullInfo("2026-10-06T09:00:00Z", "copilot-swe-agent")])
    assert [_key(r) for r in rows] == [("2026-10-05", "copilot", "pr_author_bot", 1, 0)]


def test_items_before_since_week_are_excluded():
    rows = _build(
        commits=[CommitInfo("2026-09-20T10:00:00Z", f"old\n\n{CLAUDE}")],
        since_week="2026-09-28",
    )
    assert rows == []


def test_boundary_commit_with_offset_lands_in_utc_week():
    rows = _build(commits=[CommitInfo("2026-09-27T23:30:00-05:00", f"x\n\n{CLAUDE}")])
    assert [_key(r) for r in rows] == [("2026-09-28", "claude-code", "commit_trailer", 1, 1)]


def test_non_ai_bot_and_unknown_author_are_not_counted():
    rows = _build(
        pulls=[
            PullInfo("2026-09-29T09:00:00Z", "dependabot[bot]"),
            PullInfo("2026-09-29T09:00:00Z", ""),
        ]
    )
    assert rows == []


def test_rows_never_carry_message_or_login_text():
    rows = _build(commits=[CommitInfo("2026-09-29T10:00:00Z", f"secret subject\n\n{CLAUDE}")])
    blob = repr(rows)
    assert "secret subject" not in blob
    assert "noreply@anthropic.com" not in blob
