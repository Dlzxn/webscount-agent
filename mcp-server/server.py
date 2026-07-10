"""
MCP server entry point.
Import order matters:
  1. mcp_instance  — creates shared mcp + browser singletons
  2. tools         — each submodule registers its @mcp.tool() on the shared mcp
  3. Run uvicorn with the MCP app + debug middleware

NOTE: do NOT force SelectorEventLoop on Windows here. Playwright launches
Chromium via asyncio.create_subprocess_exec, which requires the default
ProactorEventLoop; on SelectorEventLoop it raises a bare NotImplementedError.
"""

import asyncio
import logging
import os
import time

import uvicorn
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_instance import mcp
import tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("mcp.debug")


class ConnectionDebugMiddleware:
    """ASGI middleware that logs every receive() event to trace ClientDisconnect."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            method = scope.get("method", "?")
            path = scope.get("path", "?")
            client = scope.get("client", ("?", 0))
            t0 = time.monotonic()

            async def debug_receive():
                msg = await receive()
                elapsed = (time.monotonic() - t0) * 1000
                msg_type = msg.get("type", "?")
                if msg_type == "http.request":
                    body = msg.get("body", b"")
                    more = msg.get("more_body", False)
                    logger.info(
                        "  RECV %s %s from %s:%s  type=%s body_len=%d more_body=%s (%.1fms)",
                        method, path, client[0], client[1],
                        msg_type, len(body), more, elapsed,
                    )
                elif msg_type == "http.disconnect":
                    logger.warning(
                        "  RECV %s %s from %s:%s  type=HTTP_DISCONNECT (%.1fms)",
                        method, path, client[0], client[1], elapsed,
                    )
                else:
                    logger.info(
                        "  RECV %s %s from %s:%s  type=%s (%.1fms)",
                        method, path, client[0], client[1], msg_type, elapsed,
                    )
                return msg

            await self.app(scope, debug_receive, send)
        else:
            await self.app(scope, receive, send)


_mcp_app = mcp.streamable_http_app()
app = ConnectionDebugMiddleware(_mcp_app)

_host = os.environ.get("MCP_HOST", "127.0.0.1")
logger.info("Starting MCP server on %s:8000", _host)

config = uvicorn.Config(
    app,
    host=_host,
    port=8000,
    log_level="info",
)

server = uvicorn.Server(config)
asyncio.run(server.serve())
