"""FastMCP server for agentic-adoption-scan.

Registers the same 5 MCP tools as the Go mcpserver.go implementation.

Connect ASGI entrypoint: agentic_adoption_scan.server:mcp

Local testing:
    fastmcp run agentic_adoption_scan/server.py

GitHub authentication:
    On HTTP transports the server extracts the GitHub token from:
    1. ``Authorization: Bearer <token>`` header (standalone deployments)
    2. ``Posit-Connect-User-Session-Token`` header → exchanged for a
       GitHub OAuth token via ``posit-sdk`` (Connect deployments)
    3. ``GH_TOKEN`` / ``GITHUB_TOKEN`` env var (fallback for stdio)

Configuration:
    CACHE_DIR  – directory for scan-state cache (default: .agentic-scan-cache)
    CONFIG_PATH – path to indicators config YAML (default: "")
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context

from agentic_adoption_scan.cache import Cache
from agentic_adoption_scan.config import load_config, resolve_indicators
from agentic_adoption_scan.github import GitHubClient, RateLimitTracker
from agentic_adoption_scan.inspector import Inspector, summarize_content
from agentic_adoption_scan.scanner import Scanner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level config (from env vars with sensible defaults)
# ---------------------------------------------------------------------------

CACHE_DIR: str = os.environ.get("CACHE_DIR", ".agentic-scan-cache")
CONFIG_PATH: str = os.environ.get("CONFIG_PATH", "")

# Shared rate-limit tracker across all tool invocations
_rate_limit_tracker = RateLimitTracker()

# ---------------------------------------------------------------------------
# FastMCP app — ASGI entrypoint
# ---------------------------------------------------------------------------

mcp = FastMCP("agentic-adoption-scan")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_indicators_from_config(config_path: str):
    """Load indicators, optionally from *config_path*."""
    if config_path:
        cfg = load_config(config_path)
        return resolve_indicators(cfg)
    return resolve_indicators(None)


def _extract_github_token(ctx: Optional[Context]) -> str:
    """Extract a GitHub token from the MCP request context.

    Tries, in order:
    1. ``Authorization: Bearer <token>`` header (standalone HTTP deployments)
    2. ``Posit-Connect-User-Session-Token`` header → exchanged for a GitHub
       OAuth token via ``posit-sdk`` (Connect deployments with viewer OAuth)
    3. Empty string (falls through to env-var lookup in GitHubClient)
    """
    if ctx is None:
        return ""

    # Access the RequestContext via the public .request_context property.
    # The .request field on RequestContext holds the Starlette Request for
    # HTTP transports (None for stdio).  We use getattr defensively since
    # the mcp SDK could restructure internals across versions.
    req_ctx = getattr(ctx, "request_context", None)
    if req_ctx is None:
        return ""

    request = getattr(req_ctx, "request", None)
    if request is None:
        return ""

    headers = getattr(request, "headers", {})

    # 1. Direct Bearer token (standalone HTTP)
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token

    # 2. Connect credential exchange
    session_token = headers.get("posit-connect-user-session-token", "")
    if session_token:
        return _exchange_connect_token(session_token)

    return ""


def _exchange_connect_token(session_token: str) -> str:
    """Exchange a Posit Connect user session token for a GitHub OAuth token.

    Requires the ``posit-sdk`` package and a GitHub viewer OAuth integration
    configured in Connect.  Returns empty string on failure.
    """
    try:
        from posit import connect  # type: ignore[import-untyped]

        client = connect.Client()
        credentials = client.oauth.get_credentials(session_token)
        return credentials.get("access_token", "")
    except ImportError:
        logger.debug("posit-sdk not installed; skipping Connect credential exchange")
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Connect credential exchange failed: %s", exc)
        return ""


def _make_github_client(ctx: Optional[Context] = None) -> GitHubClient:
    """Create a GitHubClient from the request context (or env-var fallback)."""
    token = _extract_github_token(ctx)
    if token:
        return GitHubClient(token=token, tracker=_rate_limit_tracker)
    return GitHubClient.from_env(tracker=_rate_limit_tracker)


def _load_cache_safe(cache_dir: str) -> Cache:
    """Load cache, returning a fresh empty cache if loading fails."""
    try:
        return Cache.load_cache(cache_dir)
    except Exception:  # noqa: BLE001
        # Build a minimal empty Cache without calling the constructor directly
        from agentic_adoption_scan.storage import parse_store_path

        store, base_path = parse_store_path(cache_dir)
        return Cache(cache_dir, store, base_path, {})


def _count_unique_repos(results) -> int:
    return len({r.repo for r in results})


# ---------------------------------------------------------------------------
# scan_org
# ---------------------------------------------------------------------------


@mcp.tool()
async def scan_org(
    org: str,
    days: int = 90,
    include_archived: bool = False,
    force: bool = False,
    found_only: bool = True,
    ctx: Context = None,
) -> str:
    """Scan a GitHub organization for agentic coding adoption indicators.

    Returns structured results showing which repos have CLAUDE.md, MCP configs,
    AI workflows, evals, and other agentic coding signals.
    """

    def _run():
        client = _make_github_client(ctx)
        cache = _load_cache_safe(CACHE_DIR)
        indicators = _resolve_indicators_from_config(CONFIG_PATH)
        cutoff = datetime.now(tz=timezone.utc)
        from datetime import timedelta

        cutoff = cutoff - timedelta(days=days)

        scanner = Scanner(
            client=client,
            cache=cache,
            org=org,
            indicators=indicators,
            active_since=cutoff,
            include_archived=include_archived,
            force=force,
        )
        results = scanner.scan()

        try:
            cache.save()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not save cache: %s", exc)

        if found_only:
            results = [r for r in results if r.found]

        response = {
            "org": org,
            "total_repos": _count_unique_repos(results),
            "total_found": len(results),
            "scan_time": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "results": [
                {
                    "scan_timestamp": r.scan_timestamp,
                    "org": r.org,
                    "repo": r.repo,
                    "repo_visibility": r.repo_visibility,
                    "repo_language": r.repo_language,
                    "repo_pushed_at": r.repo_pushed_at,
                    "category": r.category,
                    "indicator": r.indicator,
                    "found": r.found,
                    "file_path": r.file_path,
                    "details": r.details,
                }
                for r in results
            ],
        }
        return json.dumps(response, indent=2)

    return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# inspect_repo
# ---------------------------------------------------------------------------


@mcp.tool()
async def inspect_repo(
    org: str,
    repo: str,
    ctx: Context = None,
) -> str:
    """Deeply inspect the content of agentic coding indicator files found in a specific repo.

    Fetches and summarizes files like CLAUDE.md, MCP configs, workflow files, etc.
    """

    def _run():
        client = _make_github_client(ctx)
        indicators = _resolve_indicators_from_config(CONFIG_PATH)
        cache = _load_cache_safe(CACHE_DIR)

        scanner = Scanner(
            client=client,
            cache=cache,
            org=org,
            indicators=indicators,
            active_since=datetime.min.replace(tzinfo=timezone.utc),
            force=True,
        )

        # Fetch the target repo directly (avoids listing the entire org)
        try:
            target_repo = client.get_repo(org, repo)
        except RuntimeError as exc:
            if "404" in str(exc):
                raise ValueError(f"repo {repo} not found in org {org}") from exc
            raise

        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        scan_results = scanner._scan_repo(target_repo, now)

        inspector = Inspector(client=client, org=org)
        inspect_results = []

        for sr in scan_results:
            if not sr.found or not sr.file_path:
                continue
            paths = [p.strip() for p in sr.file_path.split(";") if p.strip()]
            for path in paths:
                try:
                    content = client.get_file_content(org, repo, path)
                except Exception:  # noqa: BLE001
                    continue
                content_str = content.decode(errors="replace")
                summary = summarize_content(sr.category, sr.indicator, content_str)
                inspect_results.append(
                    {
                        "scan_timestamp": now,
                        "org": org,
                        "repo": repo,
                        "category": sr.category,
                        "indicator": sr.indicator,
                        "file_path": path,
                        "content_size": len(content),
                        "content_summary": summary,
                        "raw_content": content_str,
                    }
                )

        return json.dumps(inspect_results, indent=2)

    return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# list_indicators
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_indicators() -> str:
    """List all agentic coding indicators that the scanner checks for, grouped by category."""

    def _run():
        indicators = _resolve_indicators_from_config(CONFIG_PATH)
        grouped: dict[str, list[dict]] = {}
        for ind in indicators:
            entry = {
                "category": ind.category,
                "name": ind.name,
                "search_type": ind.search_type.value,
                "target": ind.target,
                "description": ind.description,
            }
            grouped.setdefault(ind.category, []).append(entry)
        return json.dumps(grouped, indent=2)

    return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# get_repo_summary
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_repo_summary(org: str, repo: str) -> str:
    """Get a summary of agentic coding adoption for a specific repo from the most recent scan.

    Shows which indicators were found.
    """

    def _run():
        try:
            cache = Cache.load_cache(CACHE_DIR)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"no cached data available: {exc}") from exc

        results = cache.get_repo_results(org, repo)
        if results is None:
            raise RuntimeError(
                f"no cached scan data for {org}/{repo} — run scan_org first"
            )

        found = [r for r in results if r.found]
        summary = {
            "org": org,
            "repo": repo,
            "found_indicators": [
                {
                    "category": r.category,
                    "indicator": r.indicator,
                    "found": r.found,
                    "file_path": r.file_path,
                    "details": r.details,
                    "scanned_at": r.scanned_at,
                }
                for r in found
            ],
            "total_found": len(found),
        }
        return json.dumps(summary, indent=2)

    return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# get_adoption_summary
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_adoption_summary(org: str) -> str:
    """Get an aggregate summary of agentic coding adoption across an entire org from the most recent scan.

    Shows adoption counts by category and top repos.
    """

    def _run():
        try:
            cache = Cache.load_cache(CACHE_DIR)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"no cached data available: {exc}") from exc

        # Access internal data to aggregate across the org
        category_repos: dict[str, set[str]] = {}
        repo_indicators: dict[str, int] = {}
        total_repos = 0

        prefix = org + "/"
        for key, cached_repo in cache._data.items():
            if not key.startswith(prefix):
                continue
            repo_name = key[len(prefix):]
            total_repos += 1

            for ind in cached_repo.indicators:
                if not ind.found:
                    continue
                repo_indicators[repo_name] = repo_indicators.get(repo_name, 0) + 1
                category_repos.setdefault(ind.category, set()).add(repo_name)

        by_category = sorted(
            [
                {"category": cat, "repo_count": len(repos)}
                for cat, repos in category_repos.items()
            ],
            key=lambda x: x["category"],
        )

        top_repos = sorted(
            [
                {"repo": repo, "indicator_count": count}
                for repo, count in repo_indicators.items()
            ],
            key=lambda x: -x["indicator_count"],
        )[:20]

        summary = {
            "org": org,
            "total_repos": total_repos,
            "repos_with_any_indicator": len(repo_indicators),
            "by_category": by_category,
            "top_repos": top_repos,
        }
        return json.dumps(summary, indent=2)

    return await asyncio.to_thread(_run)
