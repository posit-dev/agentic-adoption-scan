from __future__ import annotations

import json

import httpx
import pytest

from agentic_adoption_scan.github import GitHubClient

HEADERS = {
    "x-ratelimit-remaining": "4990",
    "x-ratelimit-reset": "0",
    "x-ratelimit-resource": "graphql",
}


def _client(handler) -> GitHubClient:
    c = GitHubClient(token="t")
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def _ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"data": data}, headers=HEADERS)


def _commit_page(nodes, has_next=False, cursor=None):
    return {
        "repository": {
            "defaultBranchRef": {
                "target": {
                    "history": {
                        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                        "nodes": nodes,
                    }
                }
            }
        }
    }


def test_graphql_posts_json_to_graphql_endpoint():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return _ok({"ok": True})

    assert _client(handler).graphql("query { x }", {"a": 1}) == {"ok": True}
    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.github.com/graphql"
    assert seen["body"] == {"query": "query { x }", "variables": {"a": 1}}
    assert seen["auth"] == "Bearer t"


def test_graphql_errors_raise():
    def handler(request):
        return httpx.Response(200, json={"errors": [{"message": "boom"}]}, headers=HEADERS)

    with pytest.raises(RuntimeError, match="boom"):
        _client(handler).graphql("query { x }", {})


def test_fetch_commits_follows_pagination():
    cursors = []

    def handler(request):
        cursor = json.loads(request.content)["variables"]["cursor"]
        cursors.append(cursor)
        if cursor is None:
            return _ok(_commit_page([{"committedDate": "2026-09-29T10:00:00Z", "message": "a"}], True, "C1"))
        return _ok(_commit_page([{"committedDate": "2026-09-30T10:00:00Z", "message": "b"}]))

    commits = _client(handler).fetch_commits("orga", "r1", "2026-09-28T00:00:00Z")
    assert [(c.committed_date, c.message) for c in commits] == [
        ("2026-09-29T10:00:00Z", "a"),
        ("2026-09-30T10:00:00Z", "b"),
    ]
    assert cursors == [None, "C1"]


def test_fetch_commits_empty_repo_returns_no_commits():
    def handler(request):
        return _ok({"repository": {"defaultBranchRef": None}})

    assert _client(handler).fetch_commits("orga", "empty", "2026-09-28T00:00:00Z") == []


def _pr(created, updated, author, reviews=()):
    return {
        "createdAt": created,
        "updatedAt": updated,
        "author": {"login": author} if author else None,
        "reviews": {
            "nodes": [
                {"submittedAt": ts, "author": {"login": a} if a else None} for ts, a in reviews
            ]
        },
    }


def _pulls_page(nodes, has_next=False, cursor=None):
    return {
        "repository": {
            "pullRequests": {
                "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                "nodes": nodes,
            }
        }
    }


def test_fetch_pull_activity_counts_in_window_items_and_stops_at_old_prs():
    calls = []

    def handler(request):
        calls.append(1)
        return _ok(
            _pulls_page(
                [
                    # created in window, reviewed in window
                    _pr("2026-09-29T09:00:00Z", "2026-09-30T09:00:00Z", "Copilot",
                        [("2026-09-30T09:00:00Z", "copilot-pull-request-reviewer")]),
                    # created BEFORE the window, review inside it: only the review counts
                    _pr("2026-09-01T09:00:00Z", "2026-09-29T12:00:00Z", "alice",
                        [("2026-09-29T12:00:00Z", "copilot-pull-request-reviewer"),
                         ("2026-09-02T12:00:00Z", "copilot-pull-request-reviewer")]),
                    # deleted author, updated in window
                    _pr("2026-09-29T08:00:00Z", "2026-09-29T08:00:00Z", None),
                    # last updated before the window: pagination stops here
                    _pr("2026-08-01T09:00:00Z", "2026-08-02T09:00:00Z", "bob"),
                ],
                has_next=True,
                cursor="NEXT",
            )
        )

    pulls, reviews = _client(handler).fetch_pull_activity("orga", "r1", "2026-09-28T00:00:00Z")
    assert len(calls) == 1  # did not request page 2
    assert [(p.created_at, p.author_login) for p in pulls] == [
        ("2026-09-29T09:00:00Z", "Copilot"),
        ("2026-09-29T08:00:00Z", ""),
    ]
    assert [(r.submitted_at, r.author_login) for r in reviews] == [
        ("2026-09-30T09:00:00Z", "copilot-pull-request-reviewer"),
        ("2026-09-29T12:00:00Z", "copilot-pull-request-reviewer"),
    ]


def test_fetch_pull_activity_repo_with_no_pull_requests():
    def handler(request):
        return _ok({"repository": {"pullRequests": None}})

    assert _client(handler).fetch_pull_activity("orga", "r1", "2026-09-28T00:00:00Z") == ([], [])


def test_fetch_commits_stops_when_cursor_is_null():
    calls = []

    def handler(request):
        calls.append(1)
        return _ok(_commit_page([{"committedDate": "2026-09-29T10:00:00Z", "message": "a"}], True, None))

    commits = _client(handler).fetch_commits("orga", "r1", "2026-09-28T00:00:00Z")
    assert len(calls) == 1
    assert [c.message for c in commits] == ["a"]


def test_fetch_pull_activity_stops_when_cursor_is_null():
    calls = []

    def handler(request):
        calls.append(1)
        return _ok(
            _pulls_page(
                [_pr("2026-09-29T09:00:00Z", "2026-09-30T09:00:00Z", "alice")],
                has_next=True,
                cursor=None,
            )
        )

    pulls, _ = _client(handler).fetch_pull_activity("orga", "r1", "2026-09-28T00:00:00Z")
    assert len(calls) == 1
    assert [p.author_login for p in pulls] == ["alice"]


def test_api_retries_transient_502(monkeypatch):
    monkeypatch.setattr("agentic_adoption_scan.github.time.sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(502, text="bad gateway", headers=HEADERS)
        return _ok({"ok": True})

    assert _client(handler).graphql("query { x }", {}) == {"ok": True}
    assert len(calls) == 2


def test_api_gives_up_after_repeated_502(monkeypatch):
    monkeypatch.setattr("agentic_adoption_scan.github.time.sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(502, text="bad gateway", headers=HEADERS)

    with pytest.raises(RuntimeError, match="exhausted retries"):
        _client(handler).graphql("query { x }", {})
    assert len(calls) == 4
