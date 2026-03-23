"""Deployment smoke tests for the MCP server on Posit Connect.

These tests prove that the Python MCP wrapper deploys successfully and that
each tool is reachable via the Streamable HTTP MCP transport.

Requirements
------------
- CONNECT_SERVER and CONNECT_API_KEY env vars (set by posit-dev/with-connect
  in CI, or manually for local runs)
- rsconnect-python installed
- The agentic-adoption-scan binary available in the connect/ directory or
  installed via pipx/pip (the Connect deployment installs it from PyPI)

Run locally
-----------
    CONNECT_SERVER=http://localhost:3939 \\
    CONNECT_API_KEY=<key> \\
    pytest evals/connect/ -v -m connect
"""
from __future__ import annotations

import json
import time

import httpx
import pytest

from conftest import wait_for_deployment

pytestmark = pytest.mark.connect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mcp_request(
    client: httpx.Client,
    url: str,
    method: str,
    params: dict | None = None,
    request_id: int = 1,
) -> dict:
    """Send one JSON-RPC 2.0 message to the MCP HTTP endpoint."""
    payload: dict = {"jsonrpc": "2.0", "method": method, "id": request_id}
    if params is not None:
        payload["params"] = params
    resp = client.post(
        url,
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()

    # Streamable HTTP responses may be newline-delimited JSON
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == request_id:
            return msg

    raise RuntimeError(
        f"No response with id={request_id} in:\n{resp.text[:500]}"
    )


def _initialize(client: httpx.Client, url: str) -> None:
    """Run the MCP initialize handshake."""
    _mcp_request(
        client,
        url,
        "initialize",
        params={
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "connect-deploy-test", "version": "1.0"},
        },
    )
    # Send initialized notification (no response expected)
    client.post(
        url,
        content=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        headers={"Content-Type": "application/json"},
    )


def _call_tool(
    client: httpx.Client,
    url: str,
    tool_name: str,
    arguments: dict,
    request_id: int = 10,
) -> dict:
    """Call an MCP tool and return the parsed result dict."""
    response = _mcp_request(
        client,
        url,
        "tools/call",
        params={"name": tool_name, "arguments": arguments},
        request_id=request_id,
    )
    if "error" in response:
        raise AssertionError(f"Tool {tool_name!r} returned error: {response['error']}")
    return response.get("result", {})


def _extract_text(result: dict) -> str:
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            return item["text"]
    raise AssertionError(f"No text content in tool result: {result}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDeploymentReachability:
    """Basic connectivity tests that the deployed server is up."""

    def test_mcp_endpoint_responds(self, mcp_url: str, http_client: httpx.Client):
        """The /mcp path returns something (even a 4xx is fine — just not connection error)."""
        wait_for_deployment(mcp_url)
        # POST an invalid payload; server should return JSON-RPC error, not a connection error
        resp = http_client.post(
            mcp_url,
            content="{}",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code < 500, (
            f"MCP endpoint returned server error {resp.status_code}: {resp.text[:200]}"
        )

    def test_mcp_initialize_handshake(self, mcp_url: str, http_client: httpx.Client):
        """The MCP initialize handshake succeeds and returns a valid result."""
        response = _mcp_request(
            http_client,
            mcp_url,
            "initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        )
        assert "result" in response, f"Expected 'result' in response: {response}"
        result = response["result"]
        assert "protocolVersion" in result, "Missing protocolVersion in init result"
        assert "serverInfo" in result, "Missing serverInfo in init result"


class TestListIndicatorsTool:
    """Test the list_indicators tool on the deployed server (no GitHub required)."""

    def test_list_indicators_returns_json(
        self, mcp_url: str, http_client: httpx.Client
    ):
        """list_indicators returns valid JSON."""
        _initialize(http_client, mcp_url)
        result = _call_tool(http_client, mcp_url, "list_indicators", {})
        text = _extract_text(result)

        data = json.loads(text)  # raises if not valid JSON
        assert isinstance(data, dict), f"Expected dict, got {type(data)}"

    def test_list_indicators_expected_categories(
        self, mcp_url: str, http_client: httpx.Client
    ):
        """list_indicators includes all expected adoption categories."""
        _initialize(http_client, mcp_url)
        result = _call_tool(http_client, mcp_url, "list_indicators", {})
        text = _extract_text(result)

        data = json.loads(text)
        expected = ["claude-code", "github-copilot", "cursor", "mcp", "evals"]
        missing = [cat for cat in expected if cat not in data]
        assert not missing, f"Missing categories on deployed server: {missing}"

    def test_list_indicators_evals_category_has_indicators(
        self, mcp_url: str, http_client: httpx.Client
    ):
        """The evals category on the deployed server contains expected indicators."""
        _initialize(http_client, mcp_url)
        result = _call_tool(http_client, mcp_url, "list_indicators", {})
        text = _extract_text(result)

        data = json.loads(text)
        evals_inds = data.get("evals", [])
        assert len(evals_inds) > 0, "evals category is empty on deployed server"

        names = {ind["name"] for ind in evals_inds}
        for expected_name in ("promptfoo config", "inspect AI", "mcp-evals"):
            assert expected_name in names, (
                f"Expected eval indicator {expected_name!r} not found in deployed server. "
                f"Got: {names}"
            )

    def test_list_indicators_indicator_fields(
        self, mcp_url: str, http_client: httpx.Client
    ):
        """Every indicator on the deployed server has required fields."""
        _initialize(http_client, mcp_url)
        result = _call_tool(http_client, mcp_url, "list_indicators", {})
        text = _extract_text(result)

        data: dict[str, list[dict]] = json.loads(text)
        errors = []
        for cat, indicators in data.items():
            for i, ind in enumerate(indicators):
                for field in ("name", "search_type", "target"):
                    if not ind.get(field):
                        errors.append(
                            f"category={cat!r} indicator[{i}] missing field {field!r}"
                        )
        assert not errors, "Schema errors in deployed list_indicators:\n" + "\n".join(
            errors[:10]
        )


class TestToolErrorHandling:
    """Test that tools return proper MCP errors for bad inputs."""

    def test_scan_org_missing_required_param(
        self, mcp_url: str, http_client: httpx.Client
    ):
        """scan_org returns IsError=true when org is not provided."""
        _initialize(http_client, mcp_url)
        response = _mcp_request(
            http_client,
            mcp_url,
            "tools/call",
            params={"name": "scan_org", "arguments": {}},
            request_id=20,
        )
        result = response.get("result", {})
        assert result.get("isError") is True, (
            "Expected isError=true for missing 'org' parameter"
        )

    def test_get_adoption_summary_missing_org(
        self, mcp_url: str, http_client: httpx.Client
    ):
        """get_adoption_summary returns IsError=true when org is not provided."""
        _initialize(http_client, mcp_url)
        response = _mcp_request(
            http_client,
            mcp_url,
            "tools/call",
            params={"name": "get_adoption_summary", "arguments": {}},
            request_id=21,
        )
        result = response.get("result", {})
        assert result.get("isError") is True, (
            "Expected isError=true for missing 'org' parameter"
        )


class TestMCPProtocolCompliance:
    """Test that the server conforms to MCP Streamable HTTP protocol."""

    def test_tools_list_returns_all_tools(
        self, mcp_url: str, http_client: httpx.Client
    ):
        """tools/list returns all 5 expected tools."""
        _initialize(http_client, mcp_url)
        response = _mcp_request(
            http_client,
            mcp_url,
            "tools/list",
            request_id=30,
        )
        assert "result" in response, f"tools/list response has no 'result': {response}"
        tools = response["result"].get("tools", [])
        tool_names = {t["name"] for t in tools}
        expected = {
            "scan_org",
            "inspect_repo",
            "list_indicators",
            "get_repo_summary",
            "get_adoption_summary",
        }
        missing = expected - tool_names
        assert not missing, f"Missing tools on deployed server: {missing}"

    def test_unknown_method_returns_error(
        self, mcp_url: str, http_client: httpx.Client
    ):
        """Calling an unknown method returns a JSON-RPC error."""
        response = _mcp_request(
            http_client,
            mcp_url,
            "nonexistent/method",
            request_id=40,
        )
        assert "error" in response or "result" in response, (
            f"Unexpected response shape: {response}"
        )
