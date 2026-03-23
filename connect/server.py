"""Posit Connect entry point for the agentic-adoption-scan MCP server.

Connect imports this module and serves the `mcp` ASGI application object
over Streamable HTTP. Each tool delegates to the `agentic-adoption-scan`
binary (installed from PyPI alongside this module) so all scanning logic
stays in the single Go binary.

Posit Connect entrypoint: server:mcp

Local testing:
    fastmcp run server.py

GitHub authentication:
    The binary uses the `gh` CLI. Set the GITHUB_TOKEN environment variable
    in your Connect content's environment variables so `gh` can authenticate
    without interactive login.
"""
import csv
import io
import json
import subprocess
import tempfile
from collections import defaultdict

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agentic-adoption-scan")


def _run_scan(
    org: str,
    days: int = 90,
    include_archived: bool = False,
    force: bool = False,
) -> list[dict]:
    cmd = [
        "agentic-adoption-scan", "scan",
        "--org", org,
        "--days", str(days),
    ]
    if include_archived:
        cmd.append("--include-archived")
    if force:
        cmd.append("--force")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"scan failed: {result.stderr}")
    reader = csv.DictReader(io.StringIO(result.stdout))
    return list(reader)


@mcp.tool()
def scan_org(
    org: str,
    days: int = 90,
    include_archived: bool = False,
    force: bool = False,
    found_only: bool = True,
) -> str:
    """Scan a GitHub organization for agentic coding adoption indicators.
    Returns structured results showing which repos have CLAUDE.md, MCP configs,
    AI workflows, evals, and other agentic coding signals.
    """
    rows = _run_scan(org, days, include_archived, force)
    if found_only:
        rows = [r for r in rows if r.get("found", "").lower() == "true"]
    repos = {r["repo"] for r in rows}
    return json.dumps(
        {
            "org": org,
            "total_repos": len(repos),
            "total_found": len(rows),
            "results": rows,
        },
        indent=2,
    )


@mcp.tool()
def get_adoption_summary(org: str, days: int = 90) -> str:
    """Get an aggregate summary of agentic coding adoption across an entire org.
    Shows adoption counts by category and top repos by indicator count.
    """
    rows = _run_scan(org, days=days)
    found = [r for r in rows if r.get("found", "").lower() == "true"]
    total_repos = len({r["repo"] for r in rows})
    repos_with_any = len({r["repo"] for r in found})

    by_category: dict[str, set] = defaultdict(set)
    repo_counts: dict[str, int] = defaultdict(int)
    for r in found:
        by_category[r["category"]].add(r["repo"])
        repo_counts[r["repo"]] += 1

    top_repos = sorted(repo_counts.items(), key=lambda x: -x[1])[:20]

    return json.dumps(
        {
            "org": org,
            "total_repos": total_repos,
            "repos_with_any_indicator": repos_with_any,
            "by_category": [
                {"category": cat, "repo_count": len(repos)}
                for cat, repos in sorted(by_category.items())
            ],
            "top_repos": [
                {"repo": repo, "indicator_count": count}
                for repo, count in top_repos
            ],
        },
        indent=2,
    )


@mcp.tool()
def get_repo_summary(org: str, repo: str, days: int = 90) -> str:
    """Get a summary of agentic coding adoption for a specific repo.
    Shows which indicators were found.
    """
    rows = _run_scan(org, days=days)
    repo_rows = [r for r in rows if r["repo"] == repo]
    found = [r for r in repo_rows if r.get("found", "").lower() == "true"]
    return json.dumps(
        {
            "org": org,
            "repo": repo,
            "found_indicators": found,
            "total_found": len(found),
        },
        indent=2,
    )


@mcp.tool()
def inspect_repo(org: str, repo: str) -> str:
    """Deeply inspect the content of agentic coding indicator files in a specific repo.
    Fetches and summarizes files like CLAUDE.md, MCP configs, workflow files, etc.
    Note: this tool scans the entire org to locate the repo's indicators first.
    """
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        scan_path = f.name
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        inspect_path = f.name

    scan_cmd = [
        "agentic-adoption-scan", "scan",
        "--org", org,
        "--output", scan_path,
    ]
    result = subprocess.run(scan_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"scan failed: {result.stderr}")

    inspect_cmd = [
        "agentic-adoption-scan", "inspect",
        "--org", org,
        "--scan-results", scan_path,
        "--output", inspect_path,
    ]
    result = subprocess.run(inspect_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"inspect failed: {result.stderr}")

    with open(inspect_path) as f:
        reader = csv.DictReader(f)
        results = [r for r in reader if r.get("repo") == repo]

    return json.dumps(results, indent=2)


@mcp.tool()
def list_indicators() -> str:
    """List all agentic coding indicators that the scanner checks for, grouped by category."""
    result = subprocess.run(
        ["agentic-adoption-scan", "init-config", "--output", "-"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"init-config failed: {result.stderr}")
    return result.stdout
