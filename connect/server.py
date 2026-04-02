"""Posit Connect ASGI entrypoint.

Connect expects a callable ASGI app. FastMCP exposes this via
``streamable_http_app()`` which returns a Starlette application.

DNS rebinding protection is disabled because Connect acts as a reverse
proxy and handles host validation itself.

Entrypoint: server:app
"""

import os

from mcp.server.transport_security import TransportSecuritySettings

# Set CONNECT_SERVER for posit-sdk credential exchange if not already set
if "CONNECT_SERVER" not in os.environ:
    connect_server = os.environ.get("CONNECT_URL", "")
    if connect_server:
        os.environ["CONNECT_SERVER"] = connect_server

from agentic_adoption_scan.server import mcp  # noqa: E402

# Disable DNS rebinding protection — Connect validates hosts at the proxy layer
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
)

# Enable stateless mode — Connect load-balances across multiple processes,
# so session state cannot be pinned to a single process.
mcp.settings.stateless_http = True

app = mcp.streamable_http_app()
