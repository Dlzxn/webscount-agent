"""
Single source of truth for the shared mcp and browser instances.
All tools/ modules import from here to avoid circular imports.
"""

from mcp.server.fastmcp import FastMCP
from browser.session import BrowserSession

mcp: FastMCP = FastMCP("browser-automation", host="127.0.0.1", port=8000)
browser: BrowserSession = BrowserSession()
