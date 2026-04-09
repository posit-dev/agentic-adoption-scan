"""pytest fixtures for the Posit Connect deployment tests.

The fixture expects a Connect server to already be running and the following
environment variables to be set (populated by posit-dev/with-connect in CI,
or by the developer manually for local testing):

    CONNECT_SERVER   — e.g. http://localhost:3939
    CONNECT_API_KEY  — an administrator API key

The fixture deploys the Python MCP wrapper once per test session and tears it
down when the session ends. Individual tests receive the deployed content URL
and a pre-configured httpx client.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent
_CONNECT_DIR = _REPO_ROOT / "connect"

# Title used for the test deployment; cleaned up after the session
_DEPLOYMENT_TITLE = "agentic-adoption-scan-mcp-ci-test"


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.skip(
            f"Environment variable {name!r} is not set. "
            "Set CONNECT_SERVER and CONNECT_API_KEY (via posit-dev/with-connect "
            "in CI, or manually for local testing)."
        )
    return value


def _rsconnect(*args: str) -> subprocess.CompletedProcess:
    cmd = ["rsconnect", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"rsconnect failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result


@pytest.fixture(scope="session")
def connect_server() -> str:
    return _require_env("CONNECT_SERVER").rstrip("/")


@pytest.fixture(scope="session")
def connect_api_key() -> str:
    return _require_env("CONNECT_API_KEY")


@pytest.fixture(scope="session")
def deployed_content_url(connect_server: str, connect_api_key: str) -> str:
    """Deploy the MCP server to Connect and return the content URL.

    Deployment runs once per test session. The content is removed in teardown
    so CI stays clean between runs.
    """
    # Deploy using rsconnect-python
    _rsconnect(
        "deploy", "fastapi",
        "--server", connect_server,
        "--api-key", connect_api_key,
        "--entrypoint", "server:mcp",
        "--title", _DEPLOYMENT_TITLE,
        "--new",                         # always create a new deployment
        str(_CONNECT_DIR),
    )

    # Retrieve the content GUID so we can build the URL and clean up later
    result = _rsconnect(
        "content", "search",
        "--server", connect_server,
        "--api-key", connect_api_key,
        "--title-contains", _DEPLOYMENT_TITLE,
        "--format", "json",
    )

    import json
    items = json.loads(result.stdout)
    if not items:
        raise RuntimeError(
            f"Could not find deployed content with title {_DEPLOYMENT_TITLE!r}"
        )

    # Most recent deployment is first
    content_guid = items[0]["guid"]
    content_url = f"{connect_server}/content/{content_guid}"

    yield content_url

    # Teardown: delete the test deployment
    try:
        _rsconnect(
            "content", "delete",
            "--server", connect_server,
            "--api-key", connect_api_key,
            "--guid", content_guid,
            "--force",
        )
    except Exception as exc:
        # Non-fatal: CI will clean up on container shutdown anyway
        print(f"Warning: teardown failed: {exc}")


@pytest.fixture(scope="session")
def mcp_url(deployed_content_url: str) -> str:
    """Return the /mcp endpoint of the deployed server."""
    return f"{deployed_content_url}/mcp"


@pytest.fixture(scope="session")
def http_client(connect_api_key: str) -> httpx.Client:
    """An httpx client authenticated to Connect."""
    client = httpx.Client(
        headers={"Authorization": f"Key {connect_api_key}"},
        timeout=60,
    )
    try:
        yield client
    finally:
        client.close()


def wait_for_deployment(url: str, timeout: int = 120) -> None:
    """Poll the MCP endpoint until it responds or the timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=5)
            if resp.status_code < 500:
                return
        except httpx.RequestError:
            pass
        time.sleep(3)
    raise TimeoutError(f"Deployment at {url} did not become ready in {timeout}s")
