"""
MCP server entry point.
Import order matters:
  1. mcp_instance  — creates shared mcp + browser singletons
  2. tools         — each submodule registers its @mcp.tool() on the shared mcp
  3. Run uvicorn with the MCP app

NOTE: do NOT force SelectorEventLoop on Windows here. Playwright launches
Chromium via asyncio.create_subprocess_exec, which requires the default
ProactorEventLoop; on SelectorEventLoop it raises a bare NotImplementedError.
"""

import asyncio
import logging
import os

import uvicorn

from mcp_instance import mcp
import tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("mcp.server")

app = mcp.streamable_http_app()

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
