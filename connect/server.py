"""Posit Connect ASGI entrypoint.

Connect expects a callable ASGI app. FastMCP exposes this via
``streamable_http_app()`` which returns a Starlette application.

Entrypoint: server:app
"""

from agentic_adoption_scan.server import mcp

app = mcp.streamable_http_app()
