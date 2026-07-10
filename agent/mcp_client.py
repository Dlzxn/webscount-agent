"""
Domain layer: MCP server communication only.
No knowledge of LLM, WebSocket, or HTTP API.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agent.config import settings

logger = logging.getLogger("agent.mcp_client")


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
        logger.info("MCPToolClient: connecting to %s", self._url)
        read, write, _ = await self._exit_stack.enter_async_context(
            streamable_http_client(self._url)
        )
        logger.info("MCPToolClient: streamable_http_client connected, creating session")
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        logger.info("MCPToolClient: session created, initializing")
        await self._session.initialize()
        logger.info("MCPToolClient: initialized successfully")

    async def close(self) -> None:
        logger.info("MCPToolClient: closing")
        await self._exit_stack.aclose()
        self._session = None

    async def __aenter__(self) -> "MCPToolClient":
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    # ── Public API ────────────────────────────────────────────────────────────

    async def list_tools(self) -> list[dict]:
        """Returns tools in Anthropic API format (snake_case input_schema)."""
        assert self._session, "Not connected — use async with MCPToolClient()"
        logger.info("MCPToolClient: list_tools()")
        result = await self._session.list_tools()
        logger.info("MCPToolClient: list_tools() returned %d tools", len(result.tools))
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema,
            }
            for t in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict) -> str | list[dict]:
        """
        Calls a tool. Returns plain text for text-only results (cheap to
        truncate/log), or a list of Anthropic content blocks when the result
        contains images (the screenshot tool) — ready to be embedded into a
        tool_result message.
        """
        assert self._session, "Not connected — use async with MCPToolClient()"
        logger.info("MCPToolClient: call_tool(%s)", name)
        result = await self._session.call_tool(name, arguments)
        logger.info("MCPToolClient: call_tool(%s) returned", name)
        return _to_anthropic_blocks(result.content)


def _to_anthropic_blocks(contents: list) -> str | list[dict]:
    """Convert MCP content items into an Anthropic tool_result payload."""
    texts: list[str] = []
    blocks: list[dict] = []
    has_image = False
    for item in contents:
        if getattr(item, "type", "") == "image":
            has_image = True
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": item.mimeType,
                    "data": item.data,
                },
            })
        elif getattr(item, "text", None):
            texts.append(item.text)
            blocks.append({"type": "text", "text": item.text})
    if not has_image:
        return "\n".join(texts) if texts else "(инструмент не вернул текста)"
    return blocks
