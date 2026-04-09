"""CLI for agentic-adoption-scan.

Port of agentic-adoption-scan/main.go.

Entry point: agentic_adoption_scan.cli:main
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import click

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
def main() -> None:
    """Scan GitHub organizations for agentic coding tool adoption."""


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


@main.command()
@click.option("--org", required=True, help="GitHub organization to scan")
@click.option("--days", default=90, type=int, show_default=True,
              help="Only include repos with activity in last N days")
@click.option("--output", default="", help="Output file path (default: stdout)")
@click.option("--format", "output_format",
              type=click.Choice(["csv", "parquet"]), default="csv", show_default=True,
              help="Output format")
@click.option("--cache-dir", default=".agentic-scan-cache", show_default=True,
              help="Directory for scan state cache")
@click.option("--config", "config_path", default="",
              help="Path to indicators config file (YAML)")
@click.option("--include-archived", is_flag=True, default=False,
              help="Include archived repos")
@click.option("--force", is_flag=True, default=False,
              help="Bypass cache and rescan everything")
@click.option("--found-only", is_flag=True, default=False,
              help="Only return results where indicator was found")
@click.option("--verbose", is_flag=True, default=False,
              help="Enable verbose logging")
def scan(
    org: str,
    days: int,
    output: str,
    output_format: str,
    cache_dir: str,
    config_path: str,
    include_archived: bool,
    force: bool,
    found_only: bool,
    verbose: bool,
) -> None:
    """Scan a GitHub org for agentic tool adoption."""
    _setup_logging(verbose)

    from agentic_adoption_scan.cache import Cache
    from agentic_adoption_scan.config import load_config, resolve_indicators
    from agentic_adoption_scan.github import GitHubClient
    from agentic_adoption_scan.output import write_scan_csv
    from agentic_adoption_scan.parquet_io import write_scan_parquet
    from agentic_adoption_scan.scanner import Scanner
    from agentic_adoption_scan.storage import LocalStore, parse_store_path  # noqa: F401

    client = GitHubClient.from_env()

    try:
        cache = Cache.load_cache(cache_dir)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Warning: could not load cache: {exc} (starting fresh)", err=True)
        from agentic_adoption_scan.storage import parse_store_path as _parse

        _store, _base_path = _parse(cache_dir)
        cache = Cache(cache_dir, _store, _base_path, {})

    cfg = None
    if config_path:
        try:
            cfg = load_config(config_path)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"Error loading config: {exc}", err=True)
            sys.exit(1)

    try:
        indicators = resolve_indicators(cfg)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error resolving indicators: {exc}", err=True)
        sys.exit(1)

    click.echo(
        f"Using {len(indicators)} indicators"
        + (f" (config mode: {cfg.mode})" if cfg is not None else ""),
        err=True,
    )

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

    scanner = Scanner(
        client=client,
        cache=cache,
        org=org,
        indicators=indicators,
        active_since=cutoff,
        include_archived=include_archived,
        force=force,
    )

    try:
        results = scanner.scan()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if found_only:
        results = [r for r in results if r.found]

    unique_repos = len({r.repo for r in results})

    # Write output
    use_parquet = output_format == "parquet" or (output and output.endswith(".parquet"))
    if use_parquet:
        try:
            import os as _os
            import posixpath

            from agentic_adoption_scan.storage import LocalStore

            _out = output or "scan-results.parquet"
            _dir = _os.path.dirname(_os.path.abspath(_out))
            _base = _os.path.splitext(_os.path.basename(_out))[0]
            _store = LocalStore()
            write_scan_parquet(_store, posixpath.join(_dir, _base), results)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"Error writing Parquet: {exc}", err=True)
            sys.exit(1)
    else:
        import io

        if output:
            try:
                with open(output, "w", newline="", encoding="utf-8") as f:
                    write_scan_csv(f, results)
            except Exception as exc:  # noqa: BLE001
                click.echo(f"Error creating output file: {exc}", err=True)
                sys.exit(1)
        else:
            import sys as _sys

            buf = io.StringIO()
            write_scan_csv(buf, results)
            _sys.stdout.write(buf.getvalue())

    try:
        cache.save()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Warning: could not save cache: {exc}", err=True)

    click.echo(
        f"Scan complete: {len(results)} results across {unique_repos} repos", err=True
    )


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


@main.command()
@click.option("--scan-results", required=True,
              help="Path to scan results CSV or Parquet")
@click.option("--org", required=True, help="GitHub organization")
@click.option("--output", default="", help="Output file path (default: stdout)")
@click.option("--format", "output_format",
              type=click.Choice(["csv", "parquet"]), default="csv", show_default=True,
              help="Output format")
@click.option("--verbose", is_flag=True, default=False,
              help="Enable verbose logging")
def inspect(
    scan_results: str,
    org: str,
    output: str,
    output_format: str,
    verbose: bool,
) -> None:
    """Deep-inspect found indicators by fetching their file content."""
    _setup_logging(verbose)

    from agentic_adoption_scan.github import GitHubClient
    from agentic_adoption_scan.inspector import Inspector
    from agentic_adoption_scan.output import write_inspect_csv
    from agentic_adoption_scan.parquet_io import write_inspect_parquet

    client = GitHubClient.from_env()
    inspector = Inspector(client=client, org=org)

    try:
        results = inspector.inspect(scan_results)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    use_parquet = output_format == "parquet" or (output and output.endswith(".parquet"))
    if use_parquet:
        try:
            import os as _os
            import posixpath

            from agentic_adoption_scan.storage import LocalStore

            _out = output or "inspect-results.parquet"
            _dir = _os.path.dirname(_os.path.abspath(_out))
            _base = _os.path.splitext(_os.path.basename(_out))[0]
            _store = LocalStore()
            write_inspect_parquet(_store, posixpath.join(_dir, _base), results)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"Error writing Parquet: {exc}", err=True)
            sys.exit(1)
    else:
        import io

        if output:
            try:
                with open(output, "w", newline="", encoding="utf-8") as f:
                    write_inspect_csv(f, results)
            except Exception as exc:  # noqa: BLE001
                click.echo(f"Error creating output file: {exc}", err=True)
                sys.exit(1)
        else:
            import sys as _sys

            buf = io.StringIO()
            write_inspect_csv(buf, results)
            _sys.stdout.write(buf.getvalue())

    click.echo(f"Inspection complete: {len(results)} files inspected", err=True)


# ---------------------------------------------------------------------------
# compact
# ---------------------------------------------------------------------------


@main.command()
@click.option("--cache-dir", default=".agentic-scan-cache", show_default=True,
              help="Cache directory (local path or s3:// URI)")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print what would be compacted without writing")
@click.option("--keep-history", is_flag=True, default=False,
              help="Keep all historical rows instead of deduplicating to latest per org/repo")
def compact(cache_dir: str, dry_run: bool, keep_history: bool) -> None:
    """Deduplicate and compact the Parquet scan cache."""
    import posixpath

    from agentic_adoption_scan.compact import deduplicate_scan_rows
    from agentic_adoption_scan.parquet_io import read_scan_rows, write_scan_rows
    from agentic_adoption_scan.storage import parse_store_path

    store, base_path = parse_store_path(cache_dir)
    parquet_path = posixpath.join(base_path, "scan-cache.parquet")

    try:
        rows = read_scan_rows(store, parquet_path)
    except FileNotFoundError:
        click.echo("No cache file found; nothing to compact.", err=True)
        return
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error reading cache: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Read {len(rows)} rows from {parquet_path}", err=True)

    if keep_history:
        compacted = rows
        click.echo(f"Keeping all {len(compacted)} historical rows", err=True)
    else:
        compacted = deduplicate_scan_rows(rows)
        click.echo(
            f"Deduplicated to {len(compacted)} rows (latest scan per org/repo)", err=True
        )

    if dry_run:
        click.echo("Dry run: not writing changes.", err=True)
        return

    try:
        write_scan_rows(store, parquet_path, compacted)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error writing compacted cache: {exc}", err=True)
        sys.exit(1)

    click.echo("Compaction complete.", err=True)


# ---------------------------------------------------------------------------
# init-config
# ---------------------------------------------------------------------------


@main.command(name="init-config")
@click.option("--output", default="indicators.yaml", show_default=True,
              help='Output config file path (use "-" for stdout)')
def init_config(output: str) -> None:
    """Generate a starter config file with all built-in indicators."""
    from agentic_adoption_scan.config import generate_default_config

    try:
        data = generate_default_config()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error generating config: {exc}", err=True)
        sys.exit(1)

    if output == "-":
        sys.stdout.write(data)
        return

    try:
        with open(output, "w", encoding="utf-8") as f:
            f.write(data)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error writing config: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Config written to {output}", err=True)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@main.command()
@click.option("--transport",
              type=click.Choice(["stdio", "http"]), default="stdio", show_default=True,
              help="Transport to use: stdio or http")
@click.option("--port", default=None, type=int,
              help="Port to listen on (http transport only)")
@click.option("--host", default="0.0.0.0", show_default=True,
              help="Host to bind to (http transport only)")
@click.option("--cache-dir", default=".agentic-scan-cache", show_default=True,
              help="Directory for scan state cache")
@click.option("--config", "config_path", default="",
              help="Path to indicators config file (YAML)")
@click.option("--verbose", is_flag=True, default=False,
              help="Enable verbose logging")
def serve(
    transport: str,
    port: int | None,
    host: str,
    cache_dir: str,
    config_path: str,
    verbose: bool,
) -> None:
    """Start MCP server (stdio or Streamable HTTP)."""
    _setup_logging(verbose)

    # Set module-level env vars consumed by server.py
    os.environ["CACHE_DIR"] = cache_dir
    if config_path:
        os.environ["CONFIG_PATH"] = config_path

    # Import the FastMCP app (picks up env vars set above)
    from agentic_adoption_scan.server import mcp

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "http":
        resolved_port = port or int(os.environ.get("PORT", "8080"))
        try:
            import uvicorn
        except ImportError:
            click.echo(
                "uvicorn is required for HTTP transport: pip install uvicorn", err=True
            )
            sys.exit(1)
        click.echo(f"Starting MCP HTTP server on {host}:{resolved_port}", err=True)
        uvicorn.run(mcp.get_asgi_app(), host=host, port=resolved_port)
    else:
        click.echo(f"Unknown transport: {transport} (must be stdio or http)", err=True)
        sys.exit(1)
