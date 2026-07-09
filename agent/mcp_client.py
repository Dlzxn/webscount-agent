"""
Domain layer: MCP server communication only.
No knowledge of LLM, WebSocket, or HTTP API.
"""

from __future__ import annotations

from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from agent.config import settings


class MCPToolClient:
    """
    Persistent connection to the MCP server for the lifetime of one agent run.
    Use as an async context manager:

        async with MCPToolClient() as client:
            tools = await client.list_tools()
            result = await client.call_tool("navigate", {"url": "..."})
    """

    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.mcp_server_url
        self._session: ClientSession | None = None
        self._exit_stack = AsyncExitStack()

    async def connect(self) -> None:
        read, write, _ = await self._exit_stack.enter_async_context(
            streamablehttp_client(self._url)
        )
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()

    async def close(self) -> None:
        await self._exit_stack.aclose()
        self._session = None

    async def __aenter__(self) -> "MCPToolClient":
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    # ── Public API ────────────────────────────────────────────────────────────

    async def list_tools(self) -> list[dict]:
        """Returns tools in Anthropic API format."""
        assert self._session, "Not connected — use async with MCPToolClient()"
        result = await self._session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema,
            }
            for t in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Calls a tool and returns its text output."""
        assert self._session, "Not connected — use async with MCPToolClient()"
        result = await self._session.call_tool(name, arguments)
        parts = [
            content.text
            for content in result.content
            if hasattr(content, "text") and content.text
        ]
        return "\n".join(parts) if parts else "(инструмент не вернул текста)"
