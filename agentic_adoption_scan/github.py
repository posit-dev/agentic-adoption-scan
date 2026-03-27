"""GitHub API client with per-user rate limiting and retry logic.

Port of agentic-adoption-scan/github.go.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
_SEARCH_MIN_DELAY = 2.1  # seconds — stay under 30 req/min for code search


# ---------------------------------------------------------------------------
# Rate-limit state
# ---------------------------------------------------------------------------


class UserRateState:
    """Per-user rate limit state (all fields protected by lock)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.search_last_call: float = 0.0
        self.rate_limit_remain: int = 100  # assume budget until told otherwise
        self.rate_limit_reset: float = 0.0
        self.last_seen: float = time.monotonic()


class RateLimitTracker:
    """Per-user rate limit tracker, keyed by sha256(token)[:16].

    Designed to be shared across multiple GitHubClient instances (e.g. in the
    MCP HTTP server where each request carries its own Bearer token).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._per_user: dict[str, UserRateState] = {}

    def get_or_create(self, token_key: str) -> UserRateState:
        with self._lock:
            state = self._per_user.get(token_key)
            if state is not None:
                state.last_seen = time.monotonic()
                return state
            state = UserRateState()
            self._per_user[token_key] = state
            return state

    def cleanup_stale(self, max_age: float) -> None:
        """Remove entries that haven't been used within max_age seconds."""
        cutoff = time.monotonic() - max_age
        with self._lock:
            stale = [k for k, s in self._per_user.items() if s.last_seen < cutoff]
            for k in stale:
                del self._per_user[k]

    def start_cleanup(
        self,
        interval: float,
        max_age: float,
        stop_event: threading.Event,
    ) -> None:
        """Run periodic cleanup in a background daemon thread."""

        def _loop() -> None:
            while not stop_event.wait(timeout=interval):
                self.cleanup_stale(max_age)

        t = threading.Thread(target=_loop, daemon=True, name="rate-limit-cleanup")
        t.start()


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Repo:
    name: str
    full_name: str
    archived: bool
    visibility: str
    language: str
    pushed_at: str


@dataclass
class SearchResult:
    total_count: int
    items: list[dict]  # each dict has "name", "path", "html_url"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _token_key(token: str) -> str:
    """Return sha256(token)[:16] — stable, short key for a token."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _parse_link_next(header: str) -> str:
    """Extract the URL for rel="next" from a Link header value.

    Example header:
        <https://api.github.com/...?page=2>; rel="next", <...>; rel="last"
    """
    if not header:
        return ""
    for part in header.split(","):
        part = part.strip()
        segments = part.split(";")
        if len(segments) < 2:
            continue
        url_part = segments[0].strip()
        rel_part = segments[1].strip()
        if rel_part == 'rel="next"':
            # Strip angle brackets
            url_part = url_part.lstrip("<").rstrip(">")
            return url_part
    return ""


# ---------------------------------------------------------------------------
# GitHubClient
# ---------------------------------------------------------------------------


class GitHubClient:
    """Sync httpx client wrapping the GitHub REST API.

    Handles per-user rate limiting, exponential-backoff retries, and
    pagination.  Use ``from_env()`` for the common single-token case, or
    pass an explicit token for per-request auth (MCP HTTP server).
    """

    def __init__(
        self,
        token: str,
        log: Optional[logging.Logger] = None,
        tracker: Optional[RateLimitTracker] = None,
    ) -> None:
        self._token = token
        self._log = log or logger
        self._tracker = tracker
        self._client = httpx.Client(timeout=30.0)

        # Local fallback state (used when tracker is None)
        self._local_lock = threading.Lock()
        self._local_rate_limit_remain: int = 100
        self._local_rate_limit_reset: float = 0.0
        self._local_search_last_call: float = 0.0

    @classmethod
    def from_env(cls, log: Optional[logging.Logger] = None) -> "GitHubClient":
        """Create a client by reading GH_TOKEN then GITHUB_TOKEN from the environment."""
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        return cls(token=token, log=log)

    # ------------------------------------------------------------------
    # Core HTTP
    # ------------------------------------------------------------------

    def api(
        self,
        method: str,
        endpoint: str,
        accept: str = "",
    ) -> tuple[bytes, httpx.Response]:
        """Call the GitHub REST API and return (body, response).

        Raises on unrecoverable errors or after exhausting all retries.
        """
        self._wait_for_rate_limit()

        raw_url = GITHUB_API_BASE + endpoint
        if not accept:
            accept = "application/vnd.github+json"

        last_exc: Optional[Exception] = None
        for attempt in range(4):
            if attempt > 0:
                backoff = (1 << attempt)  # 2, 4, 8 seconds
                jitter = random.randint(0, 500) / 1000.0
                wait = backoff + jitter
                self._log.warning(
                    "Rate limited, retrying in %.2fs (attempt %d)", wait, attempt + 1
                )
                time.sleep(wait)

            headers: dict[str, str] = {
                "Accept": accept,
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if self._token:
                headers["Authorization"] = "Bearer " + self._token

            try:
                resp = self._client.request(method, raw_url, headers=headers)
            except httpx.RequestError as exc:
                last_exc = exc
                continue

            body = resp.content
            self._update_rate_limit(resp)

            if resp.status_code in (403, 429):
                last_exc = RuntimeError(
                    f"rate limited (HTTP {resp.status_code}): {body.decode(errors='replace')}"
                )
                continue

            if resp.status_code >= 400:
                raise RuntimeError(
                    f"github api error (HTTP {resp.status_code}): {body.decode(errors='replace')}"
                )

            return body, resp

        raise RuntimeError(f"exhausted retries: {last_exc}") from last_exc

    def api_paginated(self, endpoint: str) -> list[dict]:
        """Fetch all pages of a paginated endpoint using the Link header."""
        import json as _json

        sep = "&" if "?" in endpoint else "?"
        current = endpoint + sep + "per_page=100"
        all_items: list[dict] = []

        while current:
            body, resp = self.api("GET", current)
            items: list[dict] = _json.loads(body)
            all_items.extend(items)

            next_url = _parse_link_next(resp.headers.get("link", ""))
            if not next_url:
                break
            # Link header returns full URLs; strip the base to get an endpoint
            current = next_url.removeprefix(GITHUB_API_BASE)

        return all_items

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def list_org_repos(self, org: str) -> list[Repo]:
        self._log.info("Listing repos for org: %s", org)
        raw = self.api_paginated(f"/orgs/{org}/repos?sort=pushed&direction=desc")
        repos: list[Repo] = []
        for item in raw:
            try:
                repos.append(
                    Repo(
                        name=item.get("name", ""),
                        full_name=item.get("full_name", ""),
                        archived=bool(item.get("archived", False)),
                        visibility=item.get("visibility", ""),
                        language=item.get("language") or "",
                        pushed_at=item.get("pushed_at") or "",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self._log.warning("Failed to parse repo: %s", exc)
        self._log.info("Found %d repos in %s", len(repos), org)
        return repos

    def check_path_exists(self, owner: str, repo: str, path: str) -> tuple[bool, bool]:
        """Check if a path exists in a repo. Returns (exists, is_dir)."""
        self._log.debug("Checking path: %s/%s/%s", owner, repo, path)
        endpoint = f"/repos/{owner}/{repo}/contents/{path}"

        try:
            body, _ = self.api("GET", endpoint)
        except RuntimeError as exc:
            msg = str(exc)
            if "404" in msg or "Not Found" in msg:
                return False, False
            raise

        # Directory responses are JSON arrays
        trimmed = body.lstrip()
        if trimmed and trimmed[0:1] == b"[":
            return True, True

        # Single file response
        import json as _json

        try:
            content = _json.loads(body)
            return True, content.get("type") == "dir"
        except Exception:  # noqa: BLE001
            return True, False

    def search_code(self, org: str, repo: str, query: str) -> SearchResult:
        """Search for code in a specific repo using the Code Search API."""
        self._throttle_search()
        self._log.debug("Code search in %s/%s: %s", org, repo, query)

        import json as _json

        full_query = f"{query} repo:{org}/{repo}"
        encoded = urllib.parse.quote(full_query)

        body, _ = self.api("GET", f"/search/code?q={encoded}")
        data = _json.loads(body)

        items = [
            {
                "name": i.get("name", ""),
                "path": i.get("path", ""),
                "html_url": i.get("html_url", ""),
            }
            for i in data.get("items", [])
        ]
        return SearchResult(total_count=data.get("total_count", 0), items=items)

    def search_code_in_workflows(self, org: str, repo: str, query: str) -> SearchResult:
        """Search for patterns specifically inside .github/workflows."""
        return self.search_code(org, repo, f"{query} path:.github/workflows")

    def get_file_content(self, owner: str, repo: str, path: str) -> bytes:
        """Fetch the raw content of a file from a repo."""
        self._log.debug("Fetching content: %s/%s/%s", owner, repo, path)
        endpoint = f"/repos/{owner}/{repo}/contents/{path}"
        body, _ = self.api("GET", endpoint, accept="application/vnd.github.raw+json")
        return body

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _throttle_search(self) -> None:
        """Enforce the code search rate limit (≥2100 ms between calls)."""
        if self._tracker is not None:
            key = _token_key(self._token)
            state = self._tracker.get_or_create(key)

            # Read state under per-user lock, sleep OUTSIDE the lock
            with state.lock:
                elapsed = time.monotonic() - state.search_last_call

            if elapsed < _SEARCH_MIN_DELAY:
                wait = _SEARCH_MIN_DELAY - elapsed
                self._log.debug("Throttling search: waiting %.3fs", wait)
                time.sleep(wait)

            with state.lock:
                state.search_last_call = time.monotonic()
            return

        # Local fallback
        with self._local_lock:
            elapsed = time.monotonic() - self._local_search_last_call

        if elapsed < _SEARCH_MIN_DELAY:
            wait = _SEARCH_MIN_DELAY - elapsed
            self._log.debug("Throttling search: waiting %.3fs", wait)
            time.sleep(wait)

        with self._local_lock:
            self._local_search_last_call = time.monotonic()

    def _wait_for_rate_limit(self) -> None:
        """Sleep until the rate limit resets if remaining requests are low."""
        if self._tracker is not None:
            key = _token_key(self._token)
            state = self._tracker.get_or_create(key)

            # Read state under per-user lock, sleep OUTSIDE the lock
            with state.lock:
                should_wait = (
                    state.rate_limit_remain < 10
                    and state.rate_limit_reset > time.time()
                )
                wait = (state.rate_limit_reset - time.time() + 1.0) if should_wait else 0.0

            if should_wait:
                self._log.warning("Rate limit low, waiting %.1fs until reset", wait)
                time.sleep(wait)
            return

        # Local fallback
        with self._local_lock:
            should_wait = (
                self._local_rate_limit_remain < 10
                and self._local_rate_limit_reset > time.time()
            )
            wait = (
                (self._local_rate_limit_reset - time.time() + 1.0) if should_wait else 0.0
            )

        if should_wait:
            self._log.warning(
                "Rate limit low (%d remaining), waiting %.1fs until reset",
                self._local_rate_limit_remain,
                wait,
            )
            time.sleep(wait)

    def _update_rate_limit(self, resp: httpx.Response) -> None:
        """Parse X-RateLimit-Remaining and X-RateLimit-Reset response headers."""
        remain_str = resp.headers.get("x-ratelimit-remaining", "")
        reset_str = resp.headers.get("x-ratelimit-reset", "")

        if not remain_str and not reset_str:
            return

        remain = -1
        if remain_str:
            try:
                remain = int(remain_str)
            except ValueError:
                pass

        reset = 0.0
        if reset_str:
            try:
                reset = float(reset_str)
            except ValueError:
                pass

        if self._tracker is not None:
            key = _token_key(self._token)
            state = self._tracker.get_or_create(key)
            with state.lock:
                if remain >= 0:
                    state.rate_limit_remain = remain
                if reset:
                    state.rate_limit_reset = reset
            return

        with self._local_lock:
            if remain >= 0:
                self._local_rate_limit_remain = remain
            if reset:
                self._local_rate_limit_reset = reset
