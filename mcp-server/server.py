"""
MCP server entry point.
Import order matters:
  1. mcp_instance  — creates shared mcp + browser singletons
  2. tools         — each submodule registers its @mcp.tool() on the shared mcp
  3. mcp.run()     — starts the HTTP transport (blocks until stopped)
"""

from mcp_instance import mcp  # noqa: F401 (also initialises browser singleton)
import tools  # noqa: F401 (registers all 11 tools via @mcp.tool() decorators)

mcp.run(transport="streamable-http")
