"""Posit Connect ASGI entrypoint.

This module re-exports the FastMCP app from the main package so Connect
can serve it as ``server:mcp`` over Streamable HTTP at ``/mcp``.
"""

from agentic_adoption_scan.server import mcp  # noqa: F401
