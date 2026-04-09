"""MCP server handler-level tests.

Tests the MCP tool functions directly (via their inner _run callables)
without network, LLM, or GitHub API access. Covers:
- list_indicators: structure, schema, content
- scan_org / inspect_repo / get_repo_summary / get_adoption_summary:
  required-param validation and cache-miss behaviour
- _extract_github_token: auth extraction from request contexts
"""
from __future__ import annotations

import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from agentic_adoption_scan.indicators import default_indicators


# ---------------------------------------------------------------------------
# list_indicators
# ---------------------------------------------------------------------------


def _call_list_indicators(config_path: str = "") -> dict:
    """Call list_indicators synchronously and return parsed JSON."""
    import asyncio
    from agentic_adoption_scan.server import list_indicators

    with patch("agentic_adoption_scan.server.CONFIG_PATH", config_path):
        raw = asyncio.run(list_indicators())
    return json.loads(raw)


class TestListIndicators:
    """Tests for the list_indicators MCP tool."""

    def test_returns_valid_json(self):
        data = _call_list_indicators()
        assert isinstance(data, dict)

    def test_expected_category_keys(self):
        data = _call_list_indicators()
        expected = [
            "claude-code",
            "github-copilot",
            "cursor",
            "mcp",
            "evals",
            "agents-config",
            "workflows-ai",
        ]
        missing = [cat for cat in expected if cat not in data]
        assert not missing, f"Missing category keys: {missing}"

    def test_every_indicator_has_required_fields(self):
        data = _call_list_indicators()
        errors = []
        for cat, indicators in data.items():
            assert isinstance(indicators, list), f"Category {cat!r} is not a list"
            for i, ind in enumerate(indicators):
                for field in ("name", "search_type", "target", "description"):
                    if not ind.get(field):
                        errors.append(
                            f"{cat}[{i}] missing field {field!r}"
                        )
        assert not errors, "Schema errors:\n" + "\n".join(errors)

    def test_indicator_count_matches_defaults(self):
        """Number of indicators in server response matches default_indicators()."""
        data = _call_list_indicators()
        total = sum(len(inds) for inds in data.values())
        assert total == len(default_indicators())

    def test_search_type_values_valid(self):
        """All search_type values are one of the known enum strings."""
        data = _call_list_indicators()
        valid_types = {"file_exists", "directory_exists", "content_search", "workflow_search"}
        for cat, indicators in data.items():
            for ind in indicators:
                assert ind["search_type"] in valid_types, (
                    f"{cat}/{ind['name']} has invalid search_type: {ind['search_type']}"
                )

    def test_each_category_has_at_least_one_indicator(self):
        data = _call_list_indicators()
        for cat, indicators in data.items():
            assert len(indicators) > 0, f"Category {cat!r} is empty"


# ---------------------------------------------------------------------------
# get_repo_summary — cache miss
# ---------------------------------------------------------------------------


class TestGetRepoSummary:
    """Tests for get_repo_summary cache-miss handling."""

    def test_cache_miss_raises_runtime_error(self):
        import asyncio
        from agentic_adoption_scan.server import get_repo_summary

        with tempfile.TemporaryDirectory() as tmp:
            with patch("agentic_adoption_scan.server.CACHE_DIR", tmp):
                with pytest.raises(RuntimeError, match="no cached"):
                    asyncio.run(get_repo_summary(org="nonexistent-org", repo="nonexistent-repo"))


# ---------------------------------------------------------------------------
# get_adoption_summary — cache miss
# ---------------------------------------------------------------------------


class TestGetAdoptionSummary:
    """Tests for get_adoption_summary with no cached data."""

    def test_empty_cache_returns_zero_totals(self):
        import asyncio
        from agentic_adoption_scan.server import get_adoption_summary

        with tempfile.TemporaryDirectory() as tmp:
            with patch("agentic_adoption_scan.server.CACHE_DIR", tmp):
                raw = asyncio.run(get_adoption_summary(org="nonexistent-org"))
                data = json.loads(raw)
                assert data["total_repos"] == 0
                assert data["repos_with_any_indicator"] == 0
                assert data["by_category"] == []
                assert data["top_repos"] == []


# ---------------------------------------------------------------------------
# _extract_github_token
# ---------------------------------------------------------------------------


class TestExtractGithubToken:
    """Tests for the _extract_github_token helper."""

    def test_none_context_returns_empty_string(self):
        from agentic_adoption_scan.server import _extract_github_token
        assert _extract_github_token(None) == ""

    def test_bearer_token_extracted(self):
        from agentic_adoption_scan.server import _extract_github_token

        ctx = MagicMock()
        req = MagicMock()
        req.headers = {"authorization": "Bearer ghp_test123"}
        ctx.request_context.request = req

        token = _extract_github_token(ctx)
        assert token == "ghp_test123"

    def test_empty_bearer_returns_empty(self):
        from agentic_adoption_scan.server import _extract_github_token

        ctx = MagicMock()
        req = MagicMock()
        req.headers = {"authorization": "Bearer   "}
        ctx.request_context.request = req

        token = _extract_github_token(ctx)
        assert token == ""

    def test_no_auth_header_returns_empty(self):
        from agentic_adoption_scan.server import _extract_github_token

        ctx = MagicMock()
        req = MagicMock()
        req.headers = {}
        ctx.request_context.request = req

        token = _extract_github_token(ctx)
        assert token == ""

    def test_no_request_context_returns_empty(self):
        from agentic_adoption_scan.server import _extract_github_token

        ctx = MagicMock(spec=[])  # no attributes
        token = _extract_github_token(ctx)
        assert token == ""


# ---------------------------------------------------------------------------
# _resolve_indicators_from_config
# ---------------------------------------------------------------------------


class TestResolveIndicatorsFromConfig:
    """Tests for the config resolution helper."""

    def test_empty_config_path_returns_defaults(self):
        from agentic_adoption_scan.server import _resolve_indicators_from_config

        indicators = _resolve_indicators_from_config("")
        assert len(indicators) == len(default_indicators())

    def test_nonexistent_config_path_raises(self):
        from agentic_adoption_scan.server import _resolve_indicators_from_config

        with pytest.raises(FileNotFoundError):
            _resolve_indicators_from_config("/nonexistent/config.yaml")
